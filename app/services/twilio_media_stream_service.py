import asyncio
import audioop
import base64
import contextlib
import io
import json
import logging
import re
import wave
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import perf_counter

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.conversation_prompts import (
    BARGE_IN_CONFIRMED,
    CALL_SUMMARY_READY,
    CUSTOMER_SPEAKING,
    GREETING,
    LISTENING,
    LISTENING_RESUMED,
    PLAYBACK_STARTED,
    PLAYBACK_CANCELLING,
    PLAYBACK_INTERRUPTED,
    SESSION_CLEANUP,
    SILENCE_DETECTED,
    TTS_FIRST_CHUNK_READY,
    TTS_REQUESTED,
    TRANSCRIBING,
    UTTERANCE_FINALIZED,
    build_identity_verification_prompt,
    build_empty_input_reply,
    build_opening_greeting,
    detect_consent_choice,
    detect_escalation_request,
    detect_resolution_choice,
    is_short_valid_intent,
    wants_goodbye,
)
from app.db.database import AsyncSessionLocal
from app.services.audio_quality_service import get_audio_quality_service
from app.services.conversation_service import ConversationReply, ConversationService
from app.services.gemini_service import GeminiService
from app.services.issue_resolution_service import get_issue_resolution_service
from app.services.realtime_service import RealtimeService, emit_latency_event, get_realtime_service
from app.services.rollout_service import get_rollout_service
from app.services.sarvam_stt_service import STTChunkStreamSession, STTResult, SarvamSTTService
from app.services.sarvam_tts_service import SarvamTTSService
from app.services.stream_vad_service import get_stream_vad_service
from app.services.twilio_service import TwilioService
from app.services.vad_service import get_vad_service
from app.utils.helpers import sanitize_spoken_text, utc_now_iso


logger = logging.getLogger(__name__)


@dataclass
class QueuedUtterance:
    turn_id: int
    mulaw_audio: bytes
    stt_mulaw_audio: bytes
    stt_chunk_count: int
    stt_result: STTResult | None
    stt_transport: str
    speech_ms: int
    received_at: str
    silence_detected_at: str | None
    utterance_finalized_at: str
    enqueued_at_perf: float


@dataclass
class StreamedAssistantSentence:
    text: str
    language_code: str


@dataclass
class MediaStreamSession:
    websocket: WebSocket
    call_sid: str
    stream_sid: str
    customer_name: str = ""
    language: str = "en-IN"
    customer_number: str | None = None
    inbound_buffer: bytearray = field(default_factory=bytearray)
    speech_active: bool = False
    speech_ms: int = 0
    silence_ms: int = 0
    barge_in_speech_ms: int = 0
    customer_speaking: bool = False
    playback_task: asyncio.Task | None = None
    processing_task: asyncio.Task | None = None
    assistant_playback_started_at: float | None = None
    playback_started_notified: bool = False
    current_tts_codec: str = ""
    interruption_count: int = 0
    processing_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    utterance_queue: asyncio.Queue[QueuedUtterance] | None = None
    stt_chunk_stream: STTChunkStreamSession | None = None
    active_turn_id: int = 0
    assistant_response_epoch: int = 0
    last_barge_gate_reason: str = ""
    last_barge_gate_logged_at: float = 0.0
    llm_streaming_enabled: bool = True
    tts_persistent_ws_enabled: bool = False
    tts_native_mulaw_enabled: bool = False
    tts_slow_streak: int = 0
    tts_slow_mode_until: float = 0.0
    rollout_bucket: int = 0
    last_noise_reprompt_at: float = 0.0
    last_assistant_prompt_text: str = ""
    closed: bool = False


class TwilioMediaStreamService:
    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        realtime_service: RealtimeService,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.realtime_service = realtime_service
        self.twilio_service = TwilioService(settings)
        self.stt_service = SarvamSTTService(settings)
        self.tts_service = SarvamTTSService(settings)
        self.gemini_service = GeminiService(settings)
        self.audio_quality_service = get_audio_quality_service(settings)
        self.vad_service = get_vad_service(settings)
        self.stream_vad_service = get_stream_vad_service(settings)
        self.issue_resolution_service = get_issue_resolution_service()
        self.rollout_service = get_rollout_service()
        self._sessions: dict[int, MediaStreamSession] = {}
        self._tts_warmed_languages: set[str] = set()
        self._tts_warmup_lock = asyncio.Lock()

    def _spawn_session_task(self, session: MediaStreamSession, coro, *, task_kind: str) -> asyncio.Task:
        task = asyncio.create_task(coro)

        def _on_done(done_task: asyncio.Task) -> None:
            if done_task.cancelled():
                return
            try:
                exc = done_task.exception()
            except Exception:  # noqa: BLE001
                return
            if exc is None:
                return
            logger.error(
                "Session task failed call=%s kind=%s error_type=%s detail=%s",
                session.call_sid,
                task_kind,
                type(exc).__name__,
                " ".join(str(exc).split())[:240],
                exc_info=(type(exc), exc, exc.__traceback__),
            )
            emit_latency_event(
                {
                    "step": "session_task_failed",
                    "call_sid": session.call_sid,
                    "event_timestamp": utc_now_iso(),
                    "task_kind": task_kind,
                    "error_type": type(exc).__name__,
                    "error_detail": " ".join(str(exc).split())[:240],
                }
            )

        task.add_done_callback(_on_done)
        return task

    async def handle_websocket(self, websocket: WebSocket) -> None:
        await websocket.accept()
        connection_id = id(websocket)
        try:
            while True:
                raw_message = await websocket.receive_text()
                message = json.loads(raw_message)
                event_type = message.get("event")

                if event_type == "connected":
                    logger.info("Latency step=twilio_media_websocket_connected timestamp=%s", utc_now_iso())
                    emit_latency_event(
                        {
                            "step": "twilio_media_websocket_connected",
                            "event_timestamp": utc_now_iso(),
                        }
                    )
                    continue

                if event_type == "start":
                    session = await self._handle_start(websocket, message)
                    self._sessions[connection_id] = session
                    continue

                session = self._sessions.get(connection_id)
                if not session:
                    continue

                if event_type == "media":
                    await self._handle_media(session, message)
                    continue

                if event_type == "stop":
                    await self._handle_stop(session)
                    break

                if event_type == "mark":
                    logger.debug("Twilio media stream mark received call=%s mark=%s", session.call_sid, message.get("mark"))
                    continue
        except WebSocketDisconnect:
            logger.info("Twilio media stream websocket disconnected")
        finally:
            session = self._sessions.pop(connection_id, None)
            if session:
                await self._close_session(session)

    async def _handle_start(self, websocket: WebSocket, message: dict) -> MediaStreamSession:
        start = message.get("start") or {}
        custom = start.get("customParameters") or {}
        session = MediaStreamSession(
            websocket=websocket,
            call_sid=start.get("callSid") or custom.get("call_sid") or "",
            stream_sid=start.get("streamSid") or "",
            customer_name=(custom.get("customer_name") or "").strip(),
            language=(custom.get("language") or "en-IN").strip() or "en-IN",
            customer_number=(custom.get("customer_number") or "").strip() or None,
            llm_streaming_enabled=self.settings.llm_streaming,
            tts_persistent_ws_enabled=self.settings.tts_persistent_ws,
            tts_native_mulaw_enabled=self.settings.tts_native_mulaw,
        )
        rollout_decision = self.rollout_service.get_decision(session.call_sid)
        session.rollout_bucket = rollout_decision.bucket
        session.llm_streaming_enabled = rollout_decision.llm_streaming
        session.tts_persistent_ws_enabled = rollout_decision.tts_persistent_ws
        session.tts_native_mulaw_enabled = rollout_decision.tts_native_mulaw
        logger.info(
            "Latency step=twilio_media_stream_start call=%s stream=%s timestamp=%s language=%s customer_name=%s",
            session.call_sid,
            session.stream_sid,
            utc_now_iso(),
            session.language,
            session.customer_name or "unknown",
        )
        emit_latency_event(
            {
                "step": "twilio_media_stream_start",
                "call_sid": session.call_sid,
                "stream_sid": session.stream_sid,
                "event_timestamp": utc_now_iso(),
                "language": session.language,
                "customer_name": session.customer_name or "",
                "rollout_bucket": session.rollout_bucket,
                "llm_streaming_enabled": session.llm_streaming_enabled,
                "tts_persistent_ws_enabled": session.tts_persistent_ws_enabled,
                "tts_native_mulaw_enabled": session.tts_native_mulaw_enabled,
            }
        )
        if self.settings.stream_stt_enable_micro_chunking:
            session.stt_chunk_stream = await self.stt_service.open_stream(
                call_sid=session.call_sid,
                language_code=session.language,
                sample_rate=8000,
                frame_ms=self.settings.stream_webrtc_vad_frame_ms,
                chunk_ms=self.settings.stream_stt_chunk_ms,
                preroll_ms=self.settings.stream_stt_preroll_ms,
                # Keep chunking enabled but disable persistent provider STT stream for telephony
                # to avoid long timeout stalls and perceived silence.
                enable_persistent=False,
            )
        if session.tts_persistent_ws_enabled:
            with contextlib.suppress(Exception):
                await self.tts_service.open_call_stream(
                    call_sid=session.call_sid,
                    language_code=session.language,
                )
        if self.settings.tts_static_prompt_warmup:
            asyncio.create_task(self._warm_static_tts_prompts(session.language))
        session.utterance_queue = asyncio.Queue(maxsize=self.settings.stream_utterance_queue_maxsize)
        session.processing_task = self._spawn_session_task(
            session,
            self._consume_utterances(session),
            task_kind="utterance_consumer",
        )
        await self.realtime_service.publish_call_phase(session.call_sid, GREETING)
        await self.realtime_service.broadcast_call_event(
            session.call_sid,
            {
                "type": "stream_status",
                "call_sid": session.call_sid,
                "status": "connected",
                "timestamp": self._now_iso(),
            },
        )
        await self.realtime_service.broadcast_call_event(
            session.call_sid,
            {
                "type": "rollout_status",
                "call_sid": session.call_sid,
                "rollout": rollout_decision.as_payload(),
                "timestamp": self._now_iso(),
            },
        )

        async with self.session_factory() as db:
            service = self._build_conversation_service(db)
            call = await service.upsert_call(session.call_sid, None, None, status="in-progress")
            reply = await service.create_personalized_greeting_reply(
                call,
                customer_name=session.customer_name,
                language=session.language,
            )

        session.language = reply.language_code
        session.playback_task = self._spawn_session_task(
            session,
            self._play_reply(session, reply, response_epoch=session.assistant_response_epoch),
            task_kind="assistant_playback",
        )
        return session

    async def _handle_media(self, session: MediaStreamSession, message: dict) -> None:
        media = message.get("media") or {}
        payload = media.get("payload")
        if not payload:
            return

        chunk = base64.b64decode(payload)
        frame_ms = self._frame_duration_ms(chunk)
        playback_active = bool(session.playback_task and not session.playback_task.done())
        is_speech = self._is_speech_frame(chunk, during_playback=playback_active)
        if session.stt_chunk_stream is not None:
            await self.stt_service.push_mulaw_frame(session.stt_chunk_stream, frame=chunk, is_speech=is_speech)

        if playback_active:
            if is_speech:
                session.barge_in_speech_ms += frame_ms
            else:
                # Keep a short speech memory so tiny frame-level drops don't prevent barge-in.
                session.barge_in_speech_ms = max(0, session.barge_in_speech_ms - max(20, frame_ms // 2))

            if self._should_cancel_playback(session):
                await self.realtime_service.publish_call_phase(session.call_sid, BARGE_IN_CONFIRMED)
                await self._publish_interruption_status(
                    session,
                    {
                        "stage": "barge_in_confirmed",
                        "reason": "customer-speech",
                        "speech_ms": session.barge_in_speech_ms,
                    },
                )
                await self._cancel_playback(
                    session,
                    reason="customer-speech",
                    invalidate_turn=True,
                )
        else:
            session.barge_in_speech_ms = 0
            session.last_barge_gate_reason = ""
            session.last_barge_gate_logged_at = 0.0

        if is_speech:
            if not session.customer_speaking:
                session.customer_speaking = True
                await self.realtime_service.publish_call_phase(session.call_sid, CUSTOMER_SPEAKING)
                await self.realtime_service.publish_speaking_event(session.call_sid, "customer", True)
            if not session.speech_active:
                session.inbound_buffer.clear()
                session.speech_active = True
                session.speech_ms = 0
                session.silence_ms = 0
            session.inbound_buffer.extend(chunk)
            session.speech_ms += frame_ms
            session.silence_ms = 0
        elif session.speech_active:
            session.inbound_buffer.extend(chunk)
            session.silence_ms += frame_ms

        if not session.speech_active:
            return

        if session.speech_ms >= self.settings.stream_vad_max_speech_ms:
            await self._finalize_utterance(session)
            return

        if session.silence_ms >= self.settings.stream_vad_silence_ms:
            await self._finalize_utterance(session)

    async def _finalize_utterance(self, session: MediaStreamSession) -> None:
        if not session.inbound_buffer:
            return

        utterance = bytes(session.inbound_buffer)
        speech_ms = session.speech_ms
        silence_detected = session.silence_ms >= self.settings.stream_vad_silence_ms
        silence_detected_at = utc_now_iso() if silence_detected else None
        utterance_finalized_at = utc_now_iso()
        stt_mulaw_audio = b""
        stt_chunk_count = 0
        precomputed_stt: STTResult | None = None
        stt_transport = "utterance-fallback"
        if session.stt_chunk_stream is not None:
            stt_mulaw_audio, stt_chunk_count, precomputed_stt, stt_transport = await self.stt_service.finalize_utterance_chunks(
                session.stt_chunk_stream,
                language_code=session.language,
            )
        session.inbound_buffer.clear()
        session.speech_active = False
        session.speech_ms = 0
        session.silence_ms = 0
        if session.customer_speaking:
            session.customer_speaking = False
            await self.realtime_service.publish_speaking_event(session.call_sid, "customer", False)

        playback_active = bool(session.playback_task and not session.playback_task.done())
        min_speech_ms = self.settings.stream_vad_min_speech_ms
        if playback_active:
            # Allow shorter natural barge-ins ("haan", "ji", "no") during active assistant playback.
            min_speech_ms = max(180, int(self.settings.stream_vad_min_speech_ms * 0.7))
        if speech_ms < min_speech_ms:
            logger.debug(
                "Skipping short utterance for call=%s speech_ms=%s min_speech_ms=%s",
                session.call_sid,
                speech_ms,
                min_speech_ms,
            )
            if session.stt_chunk_stream is not None:
                self.stt_service.discard_utterance_chunks(session.stt_chunk_stream)
            return

        precomputed_transcript = sanitize_spoken_text(precomputed_stt.transcript) if precomputed_stt is not None else ""
        weak_playback_utterance_threshold = max(
            220,
            int(self.settings.stream_barge_in_min_speech_ms * 0.32),
        )
        if playback_active and speech_ms < weak_playback_utterance_threshold and not precomputed_transcript:
            logger.info(
                "Latency step=utterance_dropped_during_playback call=%s timestamp=%s speech_ms=%s threshold_ms=%s",
                session.call_sid,
                utterance_finalized_at,
                speech_ms,
                weak_playback_utterance_threshold,
            )
            emit_latency_event(
                {
                    "step": "utterance_dropped_during_playback",
                    "call_sid": session.call_sid,
                    "event_timestamp": utterance_finalized_at,
                    "speech_ms": speech_ms,
                    "threshold_ms": weak_playback_utterance_threshold,
                }
            )
            if session.stt_chunk_stream is not None:
                self.stt_service.discard_utterance_chunks(session.stt_chunk_stream)
            return

        turn_id = self._activate_new_turn(
            session,
            reason="utterance_finalized",
            speech_ms=speech_ms,
        )
        if playback_active:
            await self._cancel_playback(session, reason="new-user-turn-finalized")

        if stt_chunk_count:
            logger.info(
                "Latency step=stt_micro_chunks_ready call=%s timestamp=%s chunk_count=%s audio_bytes=%s",
                session.call_sid,
                utterance_finalized_at,
                stt_chunk_count,
                len(stt_mulaw_audio),
            )
            emit_latency_event(
                {
                    "step": "stt_micro_chunks_ready",
                    "call_sid": session.call_sid,
                    "event_timestamp": utterance_finalized_at,
                    "chunk_count": stt_chunk_count,
                    "audio_bytes": len(stt_mulaw_audio),
                }
            )

        if silence_detected:
            logger.info(
                "Latency step=stream_silence_detected call=%s timestamp=%s speech_ms=%s audio_bytes=%s",
                session.call_sid,
                silence_detected_at,
                speech_ms,
                len(utterance),
            )
            emit_latency_event(
                {
                    "step": "stream_silence_detected",
                    "call_sid": session.call_sid,
                    "event_timestamp": silence_detected_at,
                    "speech_ms": speech_ms,
                    "audio_bytes": len(utterance),
                }
            )
            await self.realtime_service.publish_call_phase(session.call_sid, SILENCE_DETECTED)
        logger.info(
            "Latency step=stream_utterance_finalized call=%s timestamp=%s speech_ms=%s audio_bytes=%s",
            session.call_sid,
            utterance_finalized_at,
            speech_ms,
            len(utterance),
        )
        emit_latency_event(
            {
                "step": "stream_utterance_finalized",
                "call_sid": session.call_sid,
                "event_timestamp": utterance_finalized_at,
                "speech_ms": speech_ms,
                "audio_bytes": len(utterance),
                "silence_detected": silence_detected,
            }
        )
        await self.realtime_service.publish_call_phase(session.call_sid, UTTERANCE_FINALIZED)
        await self._enqueue_utterance(
            session,
            utterance,
            turn_id=turn_id,
            stt_mulaw_audio=stt_mulaw_audio,
            stt_chunk_count=stt_chunk_count,
            stt_result=precomputed_stt,
            stt_transport=stt_transport,
            speech_ms=speech_ms,
            silence_detected_at=silence_detected_at,
            utterance_finalized_at=utterance_finalized_at,
        )

    async def _enqueue_utterance(
        self,
        session: MediaStreamSession,
        mulaw_audio: bytes,
        *,
        turn_id: int,
        stt_mulaw_audio: bytes,
        stt_chunk_count: int,
        stt_result: STTResult | None,
        stt_transport: str,
        speech_ms: int,
        silence_detected_at: str | None,
        utterance_finalized_at: str,
    ) -> None:
        queue = session.utterance_queue
        if queue is None:
            return

        if queue.full():
            try:
                dropped = queue.get_nowait()
                queue.task_done()
                logger.warning(
                    "Dropping stale queued utterance for call=%s speech_ms=%s queue_depth=%s",
                    session.call_sid,
                    dropped.speech_ms,
                    queue.qsize(),
                )
                emit_latency_event(
                    {
                        "step": "utterance_queue_drop",
                        "call_sid": session.call_sid,
                        "event_timestamp": utc_now_iso(),
                        "dropped_speech_ms": dropped.speech_ms,
                        "queue_depth": queue.qsize(),
                    }
                )
            except asyncio.QueueEmpty:
                pass

        received_at = utc_now_iso()
        queue.put_nowait(
            QueuedUtterance(
                turn_id=turn_id,
                mulaw_audio=mulaw_audio,
                stt_mulaw_audio=stt_mulaw_audio,
                stt_chunk_count=stt_chunk_count,
                stt_result=stt_result,
                stt_transport=stt_transport,
                speech_ms=speech_ms,
                received_at=received_at,
                silence_detected_at=silence_detected_at,
                utterance_finalized_at=utterance_finalized_at,
                enqueued_at_perf=perf_counter(),
            )
        )
        logger.info(
            "Latency step=utterance_queued call=%s turn_id=%s timestamp=%s speech_ms=%s queue_depth=%s audio_bytes=%s",
            session.call_sid,
            turn_id,
            received_at,
            speech_ms,
            queue.qsize(),
            len(mulaw_audio),
        )
        emit_latency_event(
            {
                "step": "utterance_queued",
                "call_sid": session.call_sid,
                "event_timestamp": received_at,
                "turn_id": turn_id,
                "speech_ms": speech_ms,
                "queue_depth": queue.qsize(),
                "audio_bytes": len(mulaw_audio),
            }
        )

    async def _consume_utterances(self, session: MediaStreamSession) -> None:
        queue = session.utterance_queue
        if queue is None:
            return

        while True:
            try:
                queued = await queue.get()
            except asyncio.CancelledError:
                raise

            try:
                queue_wait_ms = int((perf_counter() - queued.enqueued_at_perf) * 1000)
                logger.info(
                    "Latency step=utterance_dequeued call=%s timestamp=%s queue_wait_ms=%s queue_depth=%s",
                    session.call_sid,
                    utc_now_iso(),
                    queue_wait_ms,
                    queue.qsize(),
                )
                emit_latency_event(
                    {
                        "step": "utterance_dequeued",
                        "call_sid": session.call_sid,
                        "event_timestamp": utc_now_iso(),
                        "queue_wait_ms": queue_wait_ms,
                        "queue_depth": queue.qsize(),
                    }
                )
                stale_queue_threshold_ms = 900
                if queue_wait_ms > stale_queue_threshold_ms:
                    logger.warning(
                        "Dropping stale dequeued utterance for call=%s queue_wait_ms=%s remaining_queue=%s threshold_ms=%s",
                        session.call_sid,
                        queue_wait_ms,
                        queue.qsize(),
                        stale_queue_threshold_ms,
                    )
                    emit_latency_event(
                        {
                            "step": "utterance_queue_stale_drop",
                            "call_sid": session.call_sid,
                            "event_timestamp": utc_now_iso(),
                            "queue_wait_ms": queue_wait_ms,
                            "remaining_queue_depth": queue.qsize(),
                            "threshold_ms": stale_queue_threshold_ms,
                        }
                    )
                    continue
                if not self._is_turn_current(session, queued.turn_id):
                    emit_latency_event(
                        {
                            "step": "utterance_queue_turn_drop",
                            "call_sid": session.call_sid,
                            "event_timestamp": utc_now_iso(),
                            "turn_id": queued.turn_id,
                            "active_turn_id": session.assistant_response_epoch,
                            "reason": "superseded_by_newer_turn",
                        }
                    )
                    continue
                await self._process_utterance(session, queued)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Queued utterance processing failed for call=%s", session.call_sid)
            finally:
                queue.task_done()

    async def _process_utterance(self, session: MediaStreamSession, queued: QueuedUtterance) -> None:
        async with session.processing_lock:
            response_epoch = queued.turn_id
            if not self._is_turn_current(session, response_epoch):
                emit_latency_event(
                    {
                        "step": "assistant_reply_dropped",
                        "call_sid": session.call_sid,
                        "event_timestamp": utc_now_iso(),
                        "reason": "stale_turn_before_process",
                        "turn_id": response_epoch,
                        "active_turn_id": session.assistant_response_epoch,
                    }
                )
                return
            turn_started_at = perf_counter()
            logger.info(
                "Latency step=customer_audio_received call=%s turn_id=%s mode=media_stream timestamp=%s audio_bytes=%s",
                session.call_sid,
                response_epoch,
                queued.received_at,
                len(queued.mulaw_audio),
            )
            emit_latency_event(
                {
                    "step": "customer_audio_received",
                    "call_sid": session.call_sid,
                    "turn_id": response_epoch,
                    "mode": "media_stream",
                    "event_timestamp": queued.received_at,
                    "audio_bytes": len(queued.mulaw_audio),
                    "speech_ms": queued.speech_ms,
                }
            )
            await self.realtime_service.publish_call_phase(session.call_sid, TRANSCRIBING)
            selected_mulaw_audio = queued.stt_mulaw_audio or queued.mulaw_audio
            used_micro_chunks = bool(queued.stt_mulaw_audio)
            wav_audio = self._mulaw_to_wav(selected_mulaw_audio)
            if used_micro_chunks:
                logger.info(
                    "Latency step=stt_micro_chunks_selected call=%s timestamp=%s chunk_count=%s audio_bytes=%s",
                    session.call_sid,
                    utc_now_iso(),
                    queued.stt_chunk_count,
                    len(selected_mulaw_audio),
                )
                emit_latency_event(
                    {
                        "step": "stt_micro_chunks_selected",
                        "call_sid": session.call_sid,
                        "event_timestamp": utc_now_iso(),
                        "chunk_count": queued.stt_chunk_count,
                        "audio_bytes": len(selected_mulaw_audio),
                    }
                )
            if queued.stt_result is not None:
                stt_result = queued.stt_result
                logger.info(
                    "Latency step=stt_transcript_reused call=%s timestamp=%s transport=%s chunk_count=%s",
                    session.call_sid,
                    utc_now_iso(),
                    queued.stt_transport,
                    queued.stt_chunk_count,
                )
                emit_latency_event(
                    {
                        "step": "stt_transcript_reused",
                        "call_sid": session.call_sid,
                        "event_timestamp": utc_now_iso(),
                        "transport": queued.stt_transport,
                        "chunk_count": queued.stt_chunk_count,
                    }
                )
            else:
                try:
                    adaptive_stt_timeout_s = max(
                        2.0,
                        self.settings.stream_stt_turn_timeout_seconds
                        + (0.8 if queued.speech_ms >= 700 else 0.0),
                    )
                    stt_result = await asyncio.wait_for(
                        self.stt_service.transcribe(
                            audio_bytes=wav_audio,
                            filename="twilio-stream.wav",
                            # Force stable REST STT path for telephony media streams to avoid
                            # streaming-timeout stalls that create long perceived silence.
                            content_type="audio/x-wav",
                            language_code=session.language or "unknown",
                            call_sid=session.call_sid,
                            force_rest=True,
                        ),
                        timeout=adaptive_stt_timeout_s,
                    )
                except asyncio.TimeoutError:
                    logger.warning(
                        "STT turn timeout for call=%s speech_ms=%s; proceeding with empty transcript.",
                        session.call_sid,
                        queued.speech_ms,
                    )
                    emit_latency_event(
                        {
                            "step": "stt_turn_timeout",
                            "call_sid": session.call_sid,
                            "event_timestamp": utc_now_iso(),
                            "speech_ms": queued.speech_ms,
                            "audio_bytes": len(selected_mulaw_audio),
                            "timeout_seconds": adaptive_stt_timeout_s,
                        }
                    )
                    stt_result = STTResult(
                        transcript="",
                        language_code=session.language,
                        confidence=0.0,
                        confidence_source="timeout",
                        speech_detected=queued.speech_ms >= self.settings.stream_vad_min_speech_ms,
                    )
                    # One bounded retry helps recover from transient provider/network stalls.
                    retry_timeout_s = max(1.8, self.settings.stream_stt_turn_timeout_seconds * 0.6)
                    try:
                        retry_result = await asyncio.wait_for(
                            self.stt_service.transcribe(
                                audio_bytes=wav_audio,
                                filename="twilio-stream-retry.wav",
                                content_type="audio/x-wav",
                                language_code=session.language or "unknown",
                                call_sid=session.call_sid,
                                force_rest=True,
                            ),
                            timeout=retry_timeout_s,
                        )
                        stt_result = retry_result
                        logger.info(
                            "Latency step=stt_turn_timeout_retry_success call=%s timestamp=%s retry_timeout_seconds=%s",
                            session.call_sid,
                            utc_now_iso(),
                            retry_timeout_s,
                        )
                        emit_latency_event(
                            {
                                "step": "stt_turn_timeout_retry_success",
                                "call_sid": session.call_sid,
                                "event_timestamp": utc_now_iso(),
                                "retry_timeout_seconds": retry_timeout_s,
                                "speech_ms": queued.speech_ms,
                            }
                        )
                    except Exception as retry_exc:  # noqa: BLE001
                        logger.warning(
                            "STT timeout retry failed call=%s speech_ms=%s error_type=%s detail=%s",
                            session.call_sid,
                            queued.speech_ms,
                            type(retry_exc).__name__,
                            " ".join(str(retry_exc).split())[:200],
                        )
                        emit_latency_event(
                            {
                                "step": "stt_turn_timeout_retry_failed",
                                "call_sid": session.call_sid,
                                "event_timestamp": utc_now_iso(),
                                "speech_ms": queued.speech_ms,
                                "error_type": type(retry_exc).__name__,
                            }
                        )
                except Exception as exc:  # noqa: BLE001
                    error_type = type(exc).__name__
                    error_detail = " ".join(str(exc).strip().split()) or "No error details available"
                    logger.warning(
                        "STT turn failed for call=%s speech_ms=%s; proceeding with empty transcript. error_type=%s detail=%s",
                        session.call_sid,
                        queued.speech_ms,
                        error_type,
                        error_detail,
                    )
                    emit_latency_event(
                        {
                            "step": "stt_turn_failed",
                            "call_sid": session.call_sid,
                            "event_timestamp": utc_now_iso(),
                            "speech_ms": queued.speech_ms,
                            "audio_bytes": len(selected_mulaw_audio),
                            "error_type": error_type,
                            "error_detail": error_detail,
                        }
                    )
                    stt_result = STTResult(
                        transcript="",
                        language_code=session.language,
                        confidence=0.0,
                        confidence_source="error",
                        speech_detected=False,
                    )
            stt_response_at = utc_now_iso()
            silence_to_stt_ms = self._duration_ms(queued.silence_detected_at, stt_response_at)
            finalized_to_stt_ms = self._duration_ms(queued.utterance_finalized_at, stt_response_at)
            audio_to_stt_ms = self._duration_ms(queued.received_at, stt_response_at)
            logger.info(
                "Latency step=stt_transcript_ready call=%s timestamp=%s speech_ms=%s silence_to_stt_ms=%s finalized_to_stt_ms=%s audio_to_stt_ms=%s",
                session.call_sid,
                stt_response_at,
                queued.speech_ms,
                silence_to_stt_ms,
                finalized_to_stt_ms,
                audio_to_stt_ms,
            )
            emit_latency_event(
                {
                    "step": "stt_transcript_ready",
                    "call_sid": session.call_sid,
                    "event_timestamp": stt_response_at,
                    "speech_ms": queued.speech_ms,
                    "silence_to_stt_ms": silence_to_stt_ms,
                    "finalized_to_stt_ms": finalized_to_stt_ms,
                    "audio_to_stt_ms": audio_to_stt_ms,
                }
            )
            if not self._is_turn_current(session, response_epoch):
                emit_latency_event(
                    {
                        "step": "assistant_reply_dropped",
                        "call_sid": session.call_sid,
                        "event_timestamp": utc_now_iso(),
                        "reason": "stale_turn_after_stt",
                        "turn_id": response_epoch,
                        "active_turn_id": session.assistant_response_epoch,
                    }
                )
                return
            transcript = sanitize_spoken_text(stt_result.transcript)
            ignore_noise_transcript = self._should_ignore_noise_transcript(transcript)
            if (
                ignore_noise_transcript
                and stt_result.confidence_source in {"timeout", "error"}
                and queued.speech_ms >= self.settings.stream_vad_min_speech_ms
            ):
                ignore_noise_transcript = False
                emit_latency_event(
                    {
                        "step": "stt_noise_filter_override",
                        "call_sid": session.call_sid,
                        "event_timestamp": utc_now_iso(),
                        "reason": "speech_detected_timeout_or_error",
                        "speech_ms": queued.speech_ms,
                    }
                )

            should_interrupt_playback = bool(
                not ignore_noise_transcript
                and (
                    queued.speech_ms >= self.settings.stream_vad_min_speech_ms
                    or stt_result.speech_detected
                    or transcript
                )
            )
            if should_interrupt_playback and session.playback_task and not session.playback_task.done():
                # Avoid cutting assistant audio on weak/ambiguous turns.
                token_count = len(transcript.split())
                short_transcript = token_count <= 1
                low_confidence = (stt_result.confidence or 0.0) < max(0.45, self.settings.stt_confidence_threshold * 0.9)
                required_interrupt_speech_ms = self._interrupt_speech_threshold_ms(session)
                weak_barge_in = queued.speech_ms < required_interrupt_speech_ms
                if (not transcript and weak_barge_in) or (short_transcript and low_confidence and weak_barge_in):
                    should_interrupt_playback = False
                # Require stronger evidence before interrupting active TTS playback.
                if transcript and token_count < 2 and low_confidence:
                    should_interrupt_playback = False
            if should_interrupt_playback and session.playback_task and not session.playback_task.done():
                cancel_reason = "customer-utterance-finalized"
                if not transcript and (queued.speech_ms >= self.settings.stream_vad_min_speech_ms or stt_result.speech_detected):
                    cancel_reason = "customer-speech-no-transcript"
                await self._cancel_playback(session, reason=cancel_reason)
            if ignore_noise_transcript:
                logger.info(
                    "Latency step=stt_transcript_ignored call=%s timestamp=%s reason=near_empty_noise transcript_preview=%s",
                    session.call_sid,
                    utc_now_iso(),
                    transcript[:80],
                )
                emit_latency_event(
                    {
                        "step": "stt_transcript_ignored",
                        "call_sid": session.call_sid,
                        "event_timestamp": utc_now_iso(),
                        "reason": "near_empty_noise",
                        "transcript_preview": transcript[:80],
                    }
                )
                if not session.closed:
                    await self.realtime_service.publish_call_phase(session.call_sid, LISTENING)
                    await self._schedule_noise_reprompt(
                        session=session,
                        transcript_preview=transcript[:80],
                        speech_ms=queued.speech_ms,
                        silence_to_stt_ms=silence_to_stt_ms,
                    )
                return

            stream_sentence_queue: asyncio.Queue[StreamedAssistantSentence | None] | None = None
            stream_completion_future: asyncio.Future[bool] | None = None
            streamed_sentence_count = 0
            rollout_decision = self.rollout_service.get_decision(session.call_sid)
            session.llm_streaming_enabled = rollout_decision.llm_streaming
            session.tts_persistent_ws_enabled = rollout_decision.tts_persistent_ws
            session.tts_native_mulaw_enabled = rollout_decision.tts_native_mulaw

            try:
                if not self._is_turn_current(session, response_epoch):
                    emit_latency_event(
                        {
                            "step": "assistant_reply_dropped",
                            "call_sid": session.call_sid,
                            "event_timestamp": utc_now_iso(),
                            "reason": "stale_turn_before_llm",
                            "turn_id": response_epoch,
                            "active_turn_id": session.assistant_response_epoch,
                        }
                    )
                    return
                async with self.session_factory() as db:
                    service = self._build_conversation_service(db)
                    on_assistant_sentence = None
                    if session.llm_streaming_enabled:
                        stream_sentence_queue = asyncio.Queue(maxsize=12)
                        stream_completion_future = asyncio.get_running_loop().create_future()

                        async def queue_streamed_sentence(text: str, language_code: str) -> None:
                            nonlocal streamed_sentence_count
                            if response_epoch != session.assistant_response_epoch:
                                emit_latency_event(
                                    {
                                        "step": "assistant_stream_sentence_dropped",
                                        "call_sid": session.call_sid,
                                        "event_timestamp": utc_now_iso(),
                                        "reason": "stale_response_epoch",
                                    }
                                )
                                return
                            if not text.strip() or session.closed:
                                return
                            if session.playback_task is None or session.playback_task.done():
                                session.playback_task = self._spawn_session_task(
                                    session,
                                    self._play_streamed_sentences(
                                        session,
                                        sentence_queue=stream_sentence_queue,
                                        should_hangup_future=stream_completion_future,
                                        response_epoch=response_epoch,
                                    ),
                                    task_kind="assistant_streamed_playback",
                                )
                            try:
                                stream_sentence_queue.put_nowait(
                                    StreamedAssistantSentence(
                                        text=text,
                                        language_code=language_code or session.language,
                                    )
                                )
                                streamed_sentence_count += 1
                            except asyncio.QueueFull:
                                logger.warning(
                                    "Dropping streamed assistant sentence due to queue pressure call=%s queue_depth=%s",
                                    session.call_sid,
                                    stream_sentence_queue.qsize(),
                                )

                        on_assistant_sentence = queue_streamed_sentence

                    reply = await service.handle_live_transcript(
                        call_sid=session.call_sid,
                        transcript=transcript,
                        customer_name=session.customer_name,
                        from_number=session.customer_number,
                        to_number=self.settings.twilio_phone_number,
                        audio_bytes=wav_audio,
                        detected_language=stt_result.language_code,
                        confidence=stt_result.confidence,
                        confidence_source=stt_result.confidence_source,
                        speech_detected=stt_result.speech_detected,
                        on_assistant_sentence=on_assistant_sentence,
                        llm_streaming_enabled=session.llm_streaming_enabled,
                    )
            except Exception:
                if stream_completion_future is not None and not stream_completion_future.done():
                    stream_completion_future.set_result(False)
                if stream_sentence_queue is not None:
                    with contextlib.suppress(Exception):
                        await stream_sentence_queue.put(None)
                raise

            if response_epoch != session.assistant_response_epoch:
                emit_latency_event(
                    {
                        "step": "assistant_reply_dropped",
                        "call_sid": session.call_sid,
                        "event_timestamp": utc_now_iso(),
                        "reason": "stale_response_epoch",
                    }
                )
                if stream_completion_future is not None and not stream_completion_future.done():
                    stream_completion_future.set_result(False)
                if stream_sentence_queue is not None:
                    with contextlib.suppress(Exception):
                        await stream_sentence_queue.put(None)
                return

            pending_queue_depth = session.utterance_queue.qsize() if session.utterance_queue is not None else 0
            if pending_queue_depth > 0 and not reply.should_hangup:
                emit_latency_event(
                    {
                        "step": "assistant_reply_dropped",
                        "call_sid": session.call_sid,
                        "event_timestamp": utc_now_iso(),
                        "reason": "newer_customer_utterance_pending",
                        "queue_depth": pending_queue_depth,
                    }
                )
                if stream_completion_future is not None and not stream_completion_future.done():
                    stream_completion_future.set_result(False)
                if stream_sentence_queue is not None:
                    with contextlib.suppress(Exception):
                        await stream_sentence_queue.put(None)
                return

            session.language = reply.language_code
            if stream_sentence_queue is not None and stream_completion_future is not None:
                if not stream_completion_future.done():
                    stream_completion_future.set_result(reply.should_hangup)
                if streamed_sentence_count > 0:
                    await stream_sentence_queue.put(None)
                else:
                    if session.playback_task and not session.playback_task.done():
                        session.playback_task.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await session.playback_task
                    session.playback_task = self._spawn_session_task(
                        session,
                        self._play_reply(session, reply, response_epoch=response_epoch),
                        task_kind="assistant_playback",
                    )
            else:
                session.playback_task = self._spawn_session_task(
                    session,
                    self._play_reply(session, reply, response_epoch=response_epoch),
                    task_kind="assistant_playback",
                )
            logger.info(
                "Latency step=assistant_reply_ready call=%s turn_id=%s mode=media_stream started_at=%s completed_at=%s total_ms=%s",
                session.call_sid,
                response_epoch,
                queued.received_at,
                utc_now_iso(),
                int((perf_counter() - turn_started_at) * 1000),
            )
            emit_latency_event(
                {
                    "step": "assistant_reply_ready",
                    "call_sid": session.call_sid,
                    "turn_id": response_epoch,
                    "mode": "media_stream",
                    "started_at": queued.received_at,
                    "completed_at": utc_now_iso(),
                    "latency_ms": int((perf_counter() - turn_started_at) * 1000),
                }
            )

    async def _play_reply(self, session: MediaStreamSession, reply: ConversationReply, *, response_epoch: int) -> None:
        if session.closed or not self._is_turn_current(session, response_epoch):
            return

        playback_failed = False
        try:
            session.last_assistant_prompt_text = sanitize_spoken_text(reply.text, max_length=220)
            session.assistant_playback_started_at = asyncio.get_running_loop().time()
            session.barge_in_speech_ms = 0
            session.playback_started_notified = False
            await self.realtime_service.publish_speaking_event(session.call_sid, "assistant", True)
            streaming_codec = "mulaw"
            session.current_tts_codec = streaming_codec
            await self._publish_tts_status(
                session,
                {
                    "stage": "tts_requested",
                    "codec": streaming_codec,
                    "language": reply.language_code,
                    "text_preview": reply.text[:120],
                },
            )
            await self.realtime_service.publish_call_phase(session.call_sid, TTS_REQUESTED)
            max_reply_chars = max(80, int(self.settings.assistant_tts_max_chars))
            if self._is_opening_greeting_text(reply.text, reply.language_code):
                max_reply_chars = max(max_reply_chars, 260)
            cleaned_reply_text = sanitize_spoken_text(reply.text, max_length=max_reply_chars)
            # Keep short/medium replies in a single provider request for smoother, continuous playback.
            if cleaned_reply_text and len(cleaned_reply_text) <= max_reply_chars:
                sentence_max_chars = max_reply_chars
                reply_chunks = [cleaned_reply_text]
            else:
                sentence_max_chars = self._effective_sentence_limit(session)
                reply_chunks = self._chunk_reply_for_tts(reply.text, max_chars=sentence_max_chars)
            first_audio_chunk_ref = {"pending": True}
            if len(reply_chunks) > 1:
                logger.info(
                    "Latency step=assistant_tts_chunked call=%s timestamp=%s chunk_count=%s max_chars=%s",
                    session.call_sid,
                    utc_now_iso(),
                    len(reply_chunks),
                    sentence_max_chars,
                )
                emit_latency_event(
                    {
                        "step": "assistant_tts_chunked",
                        "call_sid": session.call_sid,
                        "event_timestamp": utc_now_iso(),
                        "chunk_count": len(reply_chunks),
                        "max_chars": sentence_max_chars,
                    }
                )
            for chunk_text in reply_chunks:
                if session.closed or not self._is_turn_current(session, response_epoch):
                    return
                await self._play_tts_text(
                    session=session,
                    response_epoch=response_epoch,
                    text=chunk_text,
                    language_code=reply.language_code,
                    streaming_codec=streaming_codec,
                    first_audio_chunk_ref=first_audio_chunk_ref,
                    allow_slow_mode=not self._is_critical_prompt_text(session.last_assistant_prompt_text, reply.language_code),
                    use_cache=True,
                )

            if not self._is_turn_current(session, response_epoch):
                return
            await self._send_json(
                session,
                {
                    "event": "mark",
                    "streamSid": session.stream_sid,
                    "mark": {"name": f"assistant-turn-{int(asyncio.get_running_loop().time() * 1000)}"},
                },
            )
        except asyncio.CancelledError:
            logger.info("Assistant playback cancelled for call=%s", session.call_sid)
            raise
        except Exception as exc:  # noqa: BLE001
            playback_failed = True
            logger.error(
                "Assistant playback failed call=%s error_type=%s detail=%s",
                session.call_sid,
                type(exc).__name__,
                " ".join(str(exc).split())[:240],
                exc_info=(type(exc), exc, exc.__traceback__),
            )
            emit_latency_event(
                {
                    "step": "assistant_playback_failed",
                    "call_sid": session.call_sid,
                    "event_timestamp": utc_now_iso(),
                    "error_type": type(exc).__name__,
                    "error_detail": " ".join(str(exc).split())[:240],
                }
            )
            with contextlib.suppress(Exception):
                await self._publish_tts_status(
                    session,
                    {
                        "stage": "playback_failed",
                        "codec": session.current_tts_codec or "unknown",
                        "error_type": type(exc).__name__,
                    },
                )
        finally:
            session.assistant_playback_started_at = None
            session.barge_in_speech_ms = 0
            session.playback_started_notified = False
            session.current_tts_codec = ""
            await self.realtime_service.publish_speaking_event(session.call_sid, "assistant", False)

        if playback_failed:
            if not session.closed:
                await self.realtime_service.publish_call_phase(session.call_sid, LISTENING)
            return

        if not self._is_turn_current(session, response_epoch):
            return

        if not session.closed and not reply.should_hangup:
            await self.realtime_service.publish_call_phase(session.call_sid, LISTENING)

        if reply.should_hangup:
            await asyncio.sleep(0.5)
            with contextlib.suppress(Exception):
                await asyncio.to_thread(self.twilio_service.end_call, session.call_sid)

    @staticmethod
    def _is_opening_greeting_text(text: str, language_code: str) -> bool:
        normalized_text = sanitize_spoken_text(text).lower()
        if not normalized_text:
            return False
        if language_code == "hi-IN":
            return (
                "bob card" in normalized_text
                and "आवेदन अधूरा" in normalized_text
            )
        return (
            "bob card" in normalized_text
            and "application is incomplete" in normalized_text
        )

    async def _play_streamed_sentences(
        self,
        session: MediaStreamSession,
        *,
        sentence_queue: asyncio.Queue[StreamedAssistantSentence | None],
        should_hangup_future: asyncio.Future[bool],
        response_epoch: int,
    ) -> None:
        if session.closed or not self._is_turn_current(session, response_epoch):
            return

        playback_failed = False
        should_hangup = False
        try:
            session.assistant_playback_started_at = asyncio.get_running_loop().time()
            session.barge_in_speech_ms = 0
            session.playback_started_notified = False
            await self.realtime_service.publish_speaking_event(session.call_sid, "assistant", True)
            streaming_codec = "mulaw"
            session.current_tts_codec = streaming_codec
            await self._publish_tts_status(
                session,
                {
                    "stage": "tts_requested",
                    "codec": streaming_codec,
                    "language": session.language,
                    "text_preview": "[streaming-sentences]",
                },
            )
            await self.realtime_service.publish_call_phase(session.call_sid, TTS_REQUESTED)

            first_audio_chunk_ref = {"pending": True}
            while True:
                if not self._is_turn_current(session, response_epoch):
                    break
                queued_sentence = await sentence_queue.get()
                try:
                    if queued_sentence is None:
                        break
                    if not self._is_turn_current(session, response_epoch):
                        break
                    sentence_max_chars = self._effective_sentence_limit(session)
                    text = sanitize_spoken_text(queued_sentence.text, max_length=sentence_max_chars)
                    if not text:
                        continue
                    await self._play_tts_text(
                        session=session,
                        response_epoch=response_epoch,
                        text=text,
                        language_code=queued_sentence.language_code or session.language,
                        streaming_codec=streaming_codec,
                        first_audio_chunk_ref=first_audio_chunk_ref,
                        use_cache=False,
                    )
                finally:
                    sentence_queue.task_done()

            if not self._is_turn_current(session, response_epoch):
                return
            await self._send_json(
                session,
                {
                    "event": "mark",
                    "streamSid": session.stream_sid,
                    "mark": {"name": f"assistant-turn-{int(asyncio.get_running_loop().time() * 1000)}"},
                },
            )
        except asyncio.CancelledError:
            logger.info("Assistant streamed playback cancelled for call=%s", session.call_sid)
            raise
        except Exception as exc:  # noqa: BLE001
            playback_failed = True
            logger.error(
                "Assistant streamed playback failed call=%s error_type=%s detail=%s",
                session.call_sid,
                type(exc).__name__,
                " ".join(str(exc).split())[:240],
                exc_info=(type(exc), exc, exc.__traceback__),
            )
            emit_latency_event(
                {
                    "step": "assistant_streamed_playback_failed",
                    "call_sid": session.call_sid,
                    "event_timestamp": utc_now_iso(),
                    "error_type": type(exc).__name__,
                    "error_detail": " ".join(str(exc).split())[:240],
                }
            )
        finally:
            session.assistant_playback_started_at = None
            session.barge_in_speech_ms = 0
            session.playback_started_notified = False
            session.current_tts_codec = ""
            await self.realtime_service.publish_speaking_event(session.call_sid, "assistant", False)
            if should_hangup_future.done():
                with contextlib.suppress(Exception):
                    should_hangup = bool(should_hangup_future.result())

        if playback_failed:
            if not session.closed:
                await self.realtime_service.publish_call_phase(session.call_sid, LISTENING)
            return

        if not self._is_turn_current(session, response_epoch):
            return

        if not session.closed and not should_hangup:
            await self.realtime_service.publish_call_phase(session.call_sid, LISTENING)

        if should_hangup:
            await asyncio.sleep(0.5)
            with contextlib.suppress(Exception):
                await asyncio.to_thread(self.twilio_service.end_call, session.call_sid)

    async def _play_tts_text(
        self,
        *,
        session: MediaStreamSession,
        response_epoch: int,
        text: str,
        language_code: str,
        streaming_codec: str,
        first_audio_chunk_ref: dict[str, bool],
        allow_slow_mode: bool = True,
        use_cache: bool = True,
    ) -> None:
        if streaming_codec != "mulaw":
            raise RuntimeError(f"Unsupported streaming codec for Twilio media stream: {streaming_codec}")
        if not self._is_turn_current(session, response_epoch):
            return

        mode_sequence: list[tuple[str, bool]] = [("persistent", session.tts_persistent_ws_enabled)]
        if session.tts_persistent_ws_enabled:
            mode_sequence.append(("transient_retry", False))

        last_error: Exception | None = None
        for attempt_index, (mode_name, prefer_persistent_ws) in enumerate(mode_sequence):
            started_at = perf_counter()
            total_audio_bytes = 0
            try:
                async for mulaw_audio in self.tts_service.synthesize_chunks(
                    text=text,
                    language_code=language_code,
                    call_sid=session.call_sid,
                    output_audio_codec=streaming_codec,
                    use_cache=use_cache,
                    prefer_persistent_ws=prefer_persistent_ws,
                ):
                    if not self._is_turn_current(session, response_epoch):
                        emit_latency_event(
                            {
                                "step": "assistant_audio_chunk_dropped",
                                "call_sid": session.call_sid,
                                "event_timestamp": utc_now_iso(),
                                "reason": "stale_turn",
                                "turn_id": response_epoch,
                                "active_turn_id": session.assistant_response_epoch,
                            }
                        )
                        return
                    total_audio_bytes += len(mulaw_audio)
                    if first_audio_chunk_ref.get("pending", False):
                        first_audio_chunk_ref["pending"] = False
                        await self._mark_tts_first_chunk_ready(
                            session,
                            codec=streaming_codec,
                            chunk_bytes=len(mulaw_audio),
                            chunk_kind="mulaw",
                        )
                    await self._send_mulaw_audio(session, mulaw_audio, response_epoch=response_epoch)
                if allow_slow_mode:
                    self._update_tts_slow_mode(
                        session,
                        tts_latency_ms=int((perf_counter() - started_at) * 1000),
                        audio_bytes=total_audio_bytes,
                    )
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                can_retry = attempt_index < (len(mode_sequence) - 1)
                if not can_retry:
                    raise

                logger.warning(
                    "TTS attempt failed; retrying call=%s mode=%s next_mode=%s error_type=%s detail=%s",
                    session.call_sid,
                    mode_name,
                    mode_sequence[attempt_index + 1][0],
                    type(exc).__name__,
                    " ".join(str(exc).split())[:200],
                )
                emit_latency_event(
                    {
                        "step": "assistant_tts_retry",
                        "call_sid": session.call_sid,
                        "event_timestamp": utc_now_iso(),
                        "attempt": attempt_index + 1,
                        "mode": mode_name,
                        "next_mode": mode_sequence[attempt_index + 1][0],
                        "error_type": type(exc).__name__,
                    }
                )
                # Reset persistent stream before fallback retry to avoid stale websocket state.
                if session.tts_persistent_ws_enabled:
                    with contextlib.suppress(Exception):
                        await self.tts_service.reset_call_stream(
                            session.call_sid,
                            language_code=language_code,
                        )
                continue

        if last_error is not None:
            raise last_error

    async def _cancel_playback(
        self,
        session: MediaStreamSession,
        reason: str,
        *,
        invalidate_turn: bool = False,
    ) -> None:
        if not session.playback_task or session.playback_task.done():
            return

        if invalidate_turn:
            self._invalidate_turn(session, reason=f"playback_cancel:{reason}")

        session.interruption_count += 1
        await self.realtime_service.publish_call_phase(session.call_sid, PLAYBACK_CANCELLING)
        await self._publish_tts_status(
            session,
            {
                "stage": "playback_cancelling",
                "codec": session.current_tts_codec or "unknown",
                "reason": reason,
            },
        )
        await self._publish_interruption_status(
            session,
            {
                "stage": "playback_cancelling",
                "reason": reason,
                "count": session.interruption_count,
                "speech_ms": session.barge_in_speech_ms,
            },
        )
        session.playback_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await session.playback_task
        # Reset persistent TTS stream only for hard interruption cases to avoid audible restart artifacts.
        strong_reset_speech_ms = max(self.settings.stream_barge_in_min_speech_ms + 120, 900)
        should_reset_stream = (
            session.tts_persistent_ws_enabled
            and reason in {"customer-speech-no-transcript", "customer-speech"}
            and session.barge_in_speech_ms >= strong_reset_speech_ms
        )
        if should_reset_stream:
            with contextlib.suppress(Exception):
                await self.tts_service.reset_call_stream(
                    session.call_sid,
                    language_code=session.language,
                )
        await self._send_json(
            session,
            {
                "event": "clear",
                "streamSid": session.stream_sid,
            },
        )
        await self.realtime_service.broadcast_call_event(
            session.call_sid,
            {
                "type": "stream_interrupt",
                "call_sid": session.call_sid,
                "reason": reason,
                "timestamp": self._now_iso(),
            },
        )
        await self.realtime_service.publish_call_phase(session.call_sid, PLAYBACK_INTERRUPTED)
        await self._publish_tts_status(
            session,
            {
                "stage": "playback_interrupted",
                "codec": session.current_tts_codec or "unknown",
                "reason": reason,
            },
        )
        await self._publish_interruption_status(
            session,
            {
                "stage": "playback_interrupted",
                "reason": reason,
                "count": session.interruption_count,
            },
        )
        await self.realtime_service.publish_call_phase(session.call_sid, LISTENING_RESUMED)

    async def _handle_stop(self, session: MediaStreamSession) -> None:
        await self.realtime_service.broadcast_call_event(
            session.call_sid,
            {
                "type": "stream_status",
                "call_sid": session.call_sid,
                "status": "stopped",
                "timestamp": self._now_iso(),
            },
        )
        await self.realtime_service.publish_call_phase(session.call_sid, CALL_SUMMARY_READY)
        await self.realtime_service.publish_call_summary(session.call_sid)
        await self.realtime_service.publish_call_phase(session.call_sid, SESSION_CLEANUP)
        await self._close_session(session)

    async def _close_session(self, session: MediaStreamSession) -> None:
        if session.closed:
            return

        self._invalidate_turn(session, reason="session_close", clear_queued_utterances=True)
        session.closed = True
        if session.playback_task and not session.playback_task.done():
            session.playback_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await session.playback_task
        if session.processing_task and not session.processing_task.done():
            session.processing_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await session.processing_task
        if session.stt_chunk_stream is not None:
            with contextlib.suppress(Exception):
                await self.stt_service.close_stream(session.stt_chunk_stream)
            session.stt_chunk_stream = None
        if session.tts_persistent_ws_enabled:
            with contextlib.suppress(Exception):
                await self.tts_service.close_call_stream(session.call_sid)
        if session.customer_speaking:
            await self.realtime_service.publish_speaking_event(session.call_sid, "customer", False)
        await self.realtime_service.publish_speaking_event(session.call_sid, "assistant", False)

    async def _send_json(self, session: MediaStreamSession, payload: dict) -> None:
        async with session.send_lock:
            await session.websocket.send_json(payload)

    async def _send_mulaw_audio(self, session: MediaStreamSession, mulaw_audio: bytes, *, response_epoch: int) -> None:
        if not self._is_turn_current(session, response_epoch):
            emit_latency_event(
                {
                    "step": "assistant_audio_chunk_dropped",
                    "call_sid": session.call_sid,
                    "event_timestamp": utc_now_iso(),
                    "reason": "stale_turn_before_send",
                    "turn_id": response_epoch,
                    "active_turn_id": session.assistant_response_epoch,
                }
            )
            return
        if mulaw_audio and not session.playback_started_notified:
            session.playback_started_notified = True
            await self._publish_tts_status(
                session,
                {
                    "stage": "playback_started",
                    "codec": session.current_tts_codec or "mulaw",
                    "audio_bytes": len(mulaw_audio),
                },
            )
            await self.realtime_service.publish_call_phase(session.call_sid, PLAYBACK_STARTED)
        # Larger packet size reduces websocket overhead and audible jitter.
        chunk_size = 320
        for index in range(0, len(mulaw_audio), chunk_size):
            if session.closed or not self._is_turn_current(session, response_epoch):
                if not session.closed:
                    emit_latency_event(
                        {
                            "step": "assistant_audio_chunk_dropped",
                            "call_sid": session.call_sid,
                            "event_timestamp": utc_now_iso(),
                            "reason": "stale_turn_during_send",
                            "turn_id": response_epoch,
                            "active_turn_id": session.assistant_response_epoch,
                        }
                    )
                return
            chunk = mulaw_audio[index : index + chunk_size]
            await self._send_json(
                session,
                {
                    "event": "media",
                    "streamSid": session.stream_sid,
                    "media": {
                        "payload": base64.b64encode(chunk).decode("ascii"),
                    },
                },
            )
            frame_duration_s = len(chunk) / 8000
            await asyncio.sleep(max(0.006, frame_duration_s * 0.9))

    async def _warm_static_tts_prompts(self, language_code: str) -> None:
        normalized_language = (language_code or "hi-IN").strip() or "hi-IN"
        async with self._tts_warmup_lock:
            if normalized_language in self._tts_warmed_languages:
                return
            self._tts_warmed_languages.add(normalized_language)

        # Keep warmup away from greeting playback to avoid competing with live call TTS.
        await asyncio.sleep(12.0)
        prompts = [
            build_identity_verification_prompt(language=normalized_language),
            "नमस्ते।" if normalized_language == "hi-IN" else "Hello.",
        ]
        warmup_call_sid = f"warmup-{normalized_language}"
        for text in prompts:
            with contextlib.suppress(Exception):
                await self.tts_service.synthesize_bytes(
                    text=sanitize_spoken_text(text, max_length=max(80, int(self.settings.assistant_tts_max_chars))),
                    language_code=normalized_language,
                    call_sid=warmup_call_sid,
                    output_audio_codec="mulaw",
                    use_cache=False,
                )

    def _effective_sentence_limit(self, session: MediaStreamSession) -> int:
        base_limit = max(80, int(self.settings.assistant_tts_sentence_max_chars))
        now = asyncio.get_running_loop().time()
        if now < session.tts_slow_mode_until:
            return max(70, min(base_limit, int(self.settings.assistant_tts_slow_mode_sentence_max_chars)))
        return base_limit

    def _chunk_reply_for_tts(self, text: str, *, max_chars: int) -> list[str]:
        clean_text = sanitize_spoken_text(text, max_length=max(80, int(self.settings.assistant_tts_max_chars)))
        if not clean_text:
            return []
        limit = max(70, max_chars)
        if len(clean_text) <= limit:
            return [clean_text]

        sentence_like_parts = [part.strip() for part in re.split(r"(?<=[.!?।])\s+", clean_text) if part.strip()]
        if not sentence_like_parts:
            sentence_like_parts = [clean_text]

        chunks: list[str] = []
        current = ""

        def flush_current() -> None:
            nonlocal current
            if current.strip():
                chunks.append(current.strip())
            current = ""

        for part in sentence_like_parts:
            if len(part) > limit:
                flush_current()
                words = part.split()
                window = ""
                for word in words:
                    candidate = f"{window} {word}".strip()
                    if len(candidate) <= limit:
                        window = candidate
                    else:
                        if window:
                            chunks.append(window)
                        window = word
                if window:
                    chunks.append(window)
                continue

            candidate = f"{current} {part}".strip() if current else part
            if len(candidate) <= limit:
                current = candidate
            else:
                flush_current()
                current = part

        flush_current()
        final_chunks = chunks or [clean_text]
        if len(final_chunks) > 2:
            final_chunks = [final_chunks[0], " ".join(final_chunks[1:]).strip()]
        return final_chunks

    def _update_tts_slow_mode(self, session: MediaStreamSession, *, tts_latency_ms: int, audio_bytes: int) -> None:
        threshold_ms = max(1500, int(self.settings.assistant_tts_slow_threshold_ms))
        trigger_count = max(1, int(self.settings.assistant_tts_slow_trigger_count))
        mode_seconds = max(20, int(self.settings.assistant_tts_slow_mode_seconds))
        now = asyncio.get_running_loop().time()

        if tts_latency_ms >= threshold_ms:
            session.tts_slow_streak += 1
        else:
            session.tts_slow_streak = max(0, session.tts_slow_streak - 1)

        if session.tts_slow_streak < trigger_count:
            return

        session.tts_slow_mode_until = max(session.tts_slow_mode_until, now + mode_seconds)
        session.tts_slow_streak = 0
        logger.warning(
            "Assistant TTS slow mode enabled call=%s ttl_s=%s threshold_ms=%s observed_ms=%s audio_bytes=%s",
            session.call_sid,
            mode_seconds,
            threshold_ms,
            tts_latency_ms,
            audio_bytes,
        )
        emit_latency_event(
            {
                "step": "assistant_tts_slow_mode",
                "call_sid": session.call_sid,
                "event_timestamp": self._now_iso(),
                "threshold_ms": threshold_ms,
                "observed_ms": tts_latency_ms,
                "mode_seconds": mode_seconds,
                "audio_bytes": audio_bytes,
            }
        )

    def _activate_new_turn(self, session: MediaStreamSession, *, reason: str, speech_ms: int | None = None) -> int:
        session.assistant_response_epoch += 1
        session.active_turn_id = session.assistant_response_epoch
        emit_latency_event(
            {
                "step": "assistant_turn_activated",
                "call_sid": session.call_sid,
                "event_timestamp": utc_now_iso(),
                "turn_id": session.assistant_response_epoch,
                "reason": reason,
                "speech_ms": speech_ms,
            }
        )
        return session.assistant_response_epoch

    def _invalidate_turn(self, session: MediaStreamSession, *, reason: str, clear_queued_utterances: bool = False) -> None:
        session.assistant_response_epoch += 1
        session.active_turn_id = session.assistant_response_epoch
        dropped_count = 0
        if clear_queued_utterances and session.utterance_queue is not None:
            dropped_count = self._drain_queued_utterances(session)
        emit_latency_event(
            {
                "step": "assistant_turn_invalidated",
                "call_sid": session.call_sid,
                "event_timestamp": utc_now_iso(),
                "turn_id": session.assistant_response_epoch,
                "reason": reason,
                "dropped_queued_utterances": dropped_count,
            }
        )

    @staticmethod
    def _drain_queued_utterances(session: MediaStreamSession) -> int:
        queue = session.utterance_queue
        if queue is None:
            return 0
        dropped_count = 0
        while True:
            try:
                queue.get_nowait()
                queue.task_done()
                dropped_count += 1
            except asyncio.QueueEmpty:
                break
        return dropped_count

    @staticmethod
    def _is_turn_current(session: MediaStreamSession, turn_id: int) -> bool:
        return not session.closed and turn_id == session.assistant_response_epoch

    def _interrupt_speech_threshold_ms(self, session: MediaStreamSession) -> int:
        base_required = max(180, int(self.settings.stream_barge_in_min_speech_ms * 0.42))
        if self._looks_like_short_prompt_text(session.last_assistant_prompt_text, session.language):
            return max(180, int(base_required * 0.82))
        if self._is_critical_prompt_text(session.last_assistant_prompt_text, session.language):
            return max(280, int(base_required * 1.08))
        return base_required

    def _build_conversation_service(self, session: AsyncSession) -> ConversationService:
        return ConversationService(
            session=session,
            twilio_service=self.twilio_service,
            stt_service=self.stt_service,
            gemini_service=self.gemini_service,
            tts_service=self.tts_service,
            public_url=self.settings.public_url,
            audio_quality_service=self.audio_quality_service,
            vad_service=self.vad_service,
            issue_resolution_service=self.issue_resolution_service,
            realtime_service=self.realtime_service,
            max_turns=self.settings.max_conversation_turns,
        )

    @staticmethod
    def _frame_duration_ms(mulaw_audio: bytes) -> int:
        return max(20, int((len(mulaw_audio) / 8000) * 1000))

    def _is_speech_frame(self, mulaw_audio: bytes, during_playback: bool = False) -> bool:
        return self.stream_vad_service.is_speech_frame(mulaw_audio, during_playback=during_playback)

    def _should_cancel_playback(self, session: MediaStreamSession) -> bool:
        if session.assistant_playback_started_at is None:
            return False

        loop = asyncio.get_running_loop()
        elapsed_ms = int((loop.time() - session.assistant_playback_started_at) * 1000)
        short_prompt = self._looks_like_short_prompt_text(session.last_assistant_prompt_text, session.language)
        critical_prompt = self._is_critical_prompt_text(session.last_assistant_prompt_text, session.language)
        grace_ms = max(140, int(max(self.settings.stream_barge_in_grace_ms, self.settings.barge_in_cooldown_ms) * 0.45))
        minimum_playback_ms = max(260, int(self.settings.stream_barge_in_min_playback_ms * 0.42))
        hard_floor_ms = max(120, grace_ms // 2)
        required_speech_ms = self._interrupt_speech_threshold_ms(session)

        if short_prompt:
            # Keep short prompts naturally interruptible for quick caller acknowledgements.
            grace_ms = min(grace_ms, 240)
            minimum_playback_ms = min(minimum_playback_ms, 340)
            hard_floor_ms = min(hard_floor_ms, 170)
            required_speech_ms = min(required_speech_ms, 220)
        elif critical_prompt:
            # For compliance/explanatory content, allow interruption once the first key phrase is likely heard.
            grace_ms = max(grace_ms, 320)
            minimum_playback_ms = max(minimum_playback_ms, 520)
            hard_floor_ms = max(hard_floor_ms, 230)
            required_speech_ms = max(required_speech_ms, 300)

        if session.speech_active:
            minimum_playback_ms = max(hard_floor_ms, min(minimum_playback_ms, 760))
            required_speech_ms = min(
                required_speech_ms,
                max(190, int(self._interrupt_speech_threshold_ms(session) * 0.85)),
            )
        strong_speech_ms = max(required_speech_ms + 120, int(required_speech_ms * 1.45))
        if elapsed_ms < hard_floor_ms:
            self._record_barge_in_gate_block(
                session,
                reason="before_hard_floor",
                elapsed_ms=elapsed_ms,
                required_speech_ms=required_speech_ms,
                minimum_playback_ms=minimum_playback_ms,
            )
            return False
        if elapsed_ms < grace_ms:
            self._record_barge_in_gate_block(
                session,
                reason="before_grace",
                elapsed_ms=elapsed_ms,
                required_speech_ms=required_speech_ms,
                minimum_playback_ms=minimum_playback_ms,
            )
            return False

        if elapsed_ms < minimum_playback_ms and (session.barge_in_speech_ms < strong_speech_ms or not session.speech_active):
            self._record_barge_in_gate_block(
                session,
                reason="before_min_playback_weak_speech",
                elapsed_ms=elapsed_ms,
                required_speech_ms=required_speech_ms,
                minimum_playback_ms=minimum_playback_ms,
            )
            return False

        if session.barge_in_speech_ms < required_speech_ms:
            self._record_barge_in_gate_block(
                session,
                reason="below_required_speech",
                elapsed_ms=elapsed_ms,
                required_speech_ms=required_speech_ms,
                minimum_playback_ms=minimum_playback_ms,
            )
            return False

        if session.speech_ms and session.speech_ms < required_speech_ms:
            self._record_barge_in_gate_block(
                session,
                reason="speech_window_too_short",
                elapsed_ms=elapsed_ms,
                required_speech_ms=required_speech_ms,
                minimum_playback_ms=minimum_playback_ms,
            )
            return False

        logger.info(
            "Latency step=barge_in_confirmed call=%s timestamp=%s playback_ms=%s speech_ms=%s",
            session.call_sid,
            utc_now_iso(),
            elapsed_ms,
            session.barge_in_speech_ms,
        )
        emit_latency_event(
            {
                "step": "barge_in_confirmed",
                "call_sid": session.call_sid,
                "event_timestamp": utc_now_iso(),
                "playback_ms": elapsed_ms,
                "speech_ms": session.barge_in_speech_ms,
            }
        )
        return True

    @staticmethod
    def _is_critical_prompt_text(text: str, language_code: str) -> bool:
        normalized = sanitize_spoken_text(text).lower()
        if not normalized:
            return False
        if language_code == "hi-IN":
            critical_markers = (
                "bob card से बोल",
                "आवेदन अधूरा",
                "अभी बात कर सकते",
                "क्या मैं",
                "हाँ या नहीं",
                "लिंक",
                "दोबारा भेज",
            )
        else:
            critical_markers = (
                "bobcards support",
                "application is incomplete",
                "talk briefly",
                "am i speaking",
                "yes or no",
                "resend the link",
                "share a link",
            )
        return any(marker in normalized for marker in critical_markers)

    @staticmethod
    def _looks_like_short_prompt_text(text: str, language_code: str) -> bool:
        normalized = sanitize_spoken_text(text).lower()
        if not normalized:
            return False
        if len(normalized.split()) <= 8:
            return True
        if language_code == "hi-IN":
            markers = (
                "हाँ या नहीं",
                "लिंक मिला या नहीं",
                "कृपया हाँ",
                "कृपया नहीं",
                "कृपया बताइए",
            )
        else:
            markers = (
                "yes or no",
                "link received or not",
                "please say yes",
                "please say no",
                "please tell me",
            )
        return any(marker in normalized for marker in markers)

    def _record_barge_in_gate_block(
        self,
        session: MediaStreamSession,
        *,
        reason: str,
        elapsed_ms: int,
        required_speech_ms: int,
        minimum_playback_ms: int,
    ) -> None:
        now = asyncio.get_running_loop().time()
        should_emit = (
            reason != session.last_barge_gate_reason
            or (now - session.last_barge_gate_logged_at) >= 0.25
        )
        if not should_emit:
            return

        session.last_barge_gate_reason = reason
        session.last_barge_gate_logged_at = now
        emit_latency_event(
            {
                "step": "barge_in_gate_blocked",
                "call_sid": session.call_sid,
                "event_timestamp": utc_now_iso(),
                "reason": reason,
                "playback_ms": elapsed_ms,
                "speech_ms": session.barge_in_speech_ms,
                "required_speech_ms": required_speech_ms,
                "minimum_playback_ms": minimum_playback_ms,
            }
        )

    @staticmethod
    def _mulaw_to_wav(mulaw_audio: bytes) -> bytes:
        linear_pcm = audioop.ulaw2lin(mulaw_audio, 2)
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(8000)
            wav_file.writeframes(linear_pcm)
        return buffer.getvalue()

    async def _mark_tts_first_chunk_ready(
        self,
        session: MediaStreamSession,
        *,
        codec: str,
        chunk_bytes: int,
        chunk_kind: str,
    ) -> None:
        logger.info(
            "Latency step=assistant_audio_ready call=%s mode=media_stream timestamp=%s audio_bytes=%s codec=%s",
            session.call_sid,
            utc_now_iso(),
            chunk_bytes,
            codec,
        )
        emit_latency_event(
            {
                "step": "assistant_audio_ready",
                "call_sid": session.call_sid,
                "mode": "media_stream",
                "event_timestamp": utc_now_iso(),
                "audio_bytes": chunk_bytes,
                "codec": codec,
            }
        )
        await self._publish_tts_status(
            session,
            {
                "stage": "tts_first_chunk_ready",
                "codec": codec,
                "chunk_bytes": chunk_bytes,
                "chunk_kind": chunk_kind,
            },
        )
        await self.realtime_service.publish_call_phase(session.call_sid, TTS_FIRST_CHUNK_READY)

    async def _publish_tts_status(self, session: MediaStreamSession, payload: dict) -> None:
        await self.realtime_service.publish_tts_status(
            session.call_sid,
            {
                "call_sid": session.call_sid,
                "stream_sid": session.stream_sid,
                "timestamp": self._now_iso(),
                **payload,
            },
        )

    async def _publish_interruption_status(self, session: MediaStreamSession, payload: dict) -> None:
        await self.realtime_service.publish_interruption_status(
            session.call_sid,
            {
                "call_sid": session.call_sid,
                "stream_sid": session.stream_sid,
                "timestamp": self._now_iso(),
                **payload,
            },
        )

    def _should_ignore_noise_transcript(self, transcript: str) -> bool:
        cleaned = sanitize_spoken_text(transcript)
        if not cleaned:
            return True
        normalized = re.sub(r"\s+", " ", cleaned).strip().lower()
        compact = re.sub(r"[^\w\u0900-\u097F]+", " ", normalized).strip()
        greeting_tokens = {"hello", "hi", "hii", "हलो", "हैलो", "हेलो", "नमस्ते"}
        if compact in greeting_tokens:
            return False
        if is_short_valid_intent(cleaned):
            return False
        if wants_goodbye(cleaned):
            return False
        if detect_resolution_choice(cleaned) != "unknown":
            return False
        if detect_consent_choice(cleaned) != "unknown":
            return False
        if detect_escalation_request(cleaned):
            return False
        # Avoid dropping short but valid acknowledgements such as "हेलो", "hello", "जी", etc.
        if len(compact) > 1 and any(ch.isalpha() for ch in compact):
            return False

        meaningful_chars = sum(1 for char in normalized if char.isalnum())
        if meaningful_chars < max(3, int(self.settings.empty_transcript_min_chars)):
            return True
        if len(normalized.split()) <= 1 and meaningful_chars <= 4:
            return True
        return False

    async def _schedule_noise_reprompt(
        self,
        *,
        session: MediaStreamSession,
        transcript_preview: str,
        speech_ms: int,
        silence_to_stt_ms: int | None,
    ) -> None:
        if session.closed:
            return
        if session.playback_task and not session.playback_task.done():
            return

        loop_now = asyncio.get_running_loop().time()
        # Avoid repetitive reprompts when caller stays silent/noisy.
        if (loop_now - session.last_noise_reprompt_at) < 6.0:
            return
        session.last_noise_reprompt_at = loop_now

        prompt_text = sanitize_spoken_text(
            build_empty_input_reply(session.language),
            max_length=max(40, int(self.settings.assistant_tts_max_chars)),
        )
        if not prompt_text:
            return

        logger.info(
            "Latency step=assistant_noise_reprompt call=%s timestamp=%s speech_ms=%s silence_to_stt_ms=%s transcript_preview=%s",
            session.call_sid,
            utc_now_iso(),
            speech_ms,
            silence_to_stt_ms,
            transcript_preview,
        )
        emit_latency_event(
            {
                "step": "assistant_noise_reprompt",
                "call_sid": session.call_sid,
                "event_timestamp": utc_now_iso(),
                "speech_ms": speech_ms,
                "silence_to_stt_ms": silence_to_stt_ms,
                "transcript_preview": transcript_preview,
            }
        )
        session.playback_task = self._spawn_session_task(
            session,
            self._play_reply(
                session,
                ConversationReply(
                    text=prompt_text,
                    language_code=session.language or "hi-IN",
                    should_hangup=False,
                ),
                response_epoch=session.assistant_response_epoch,
            ),
            task_kind="assistant_noise_reprompt_playback",
        )

    @staticmethod
    def _duration_ms(start_iso: str | None, end_iso: str | None) -> int | None:
        if not start_iso or not end_iso:
            return None
        try:
            started_at = datetime.fromisoformat(start_iso)
            completed_at = datetime.fromisoformat(end_iso)
        except ValueError:
            return None
        return max(0, int((completed_at - started_at).total_seconds() * 1000))

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(UTC).isoformat()


_media_stream_service: TwilioMediaStreamService | None = None


def get_twilio_media_stream_service() -> TwilioMediaStreamService:
    global _media_stream_service
    if _media_stream_service is None:
        settings = get_settings()
        _media_stream_service = TwilioMediaStreamService(
            settings=settings,
            session_factory=AsyncSessionLocal,
            realtime_service=get_realtime_service(),
        )
    return _media_stream_service
