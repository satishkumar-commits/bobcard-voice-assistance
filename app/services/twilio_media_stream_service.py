import asyncio
import audioop
import base64
import contextlib
import io
import json
import logging
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
)
from app.db.database import AsyncSessionLocal
from app.services.audio_quality_service import get_audio_quality_service
from app.services.conversation_service import ConversationReply, ConversationService
from app.services.gemini_service import GeminiService
from app.services.issue_resolution_service import get_issue_resolution_service
from app.services.realtime_service import RealtimeService, emit_latency_event, get_realtime_service
from app.services.sarvam_stt_service import STTResult, SarvamSTTService
from app.services.sarvam_tts_service import SarvamTTSService
from app.services.twilio_service import TwilioService
from app.services.vad_service import get_vad_service
from app.utils.helpers import sanitize_spoken_text, utc_now_iso


logger = logging.getLogger(__name__)


@dataclass
class QueuedUtterance:
    mulaw_audio: bytes
    speech_ms: int
    received_at: str
    enqueued_at_perf: float


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
        self.issue_resolution_service = get_issue_resolution_service()
        self._sessions: dict[int, MediaStreamSession] = {}

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
        )
        logger.info(
            "Latency step=twilio_media_stream_start call=%s stream=%s timestamp=%s language=%s",
            session.call_sid,
            session.stream_sid,
            utc_now_iso(),
            session.language,
        )
        emit_latency_event(
            {
                "step": "twilio_media_stream_start",
                "call_sid": session.call_sid,
                "stream_sid": session.stream_sid,
                "event_timestamp": utc_now_iso(),
                "language": session.language,
            }
        )
        session.utterance_queue = asyncio.Queue(maxsize=self.settings.stream_utterance_queue_maxsize)
        session.processing_task = asyncio.create_task(self._consume_utterances(session))
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

        async with self.session_factory() as db:
            service = self._build_conversation_service(db)
            call = await service.upsert_call(session.call_sid, None, None, status="in-progress")
            reply = await service.create_personalized_greeting_reply(
                call,
                customer_name=session.customer_name,
                language=session.language,
            )

        session.language = reply.language_code
        session.playback_task = asyncio.create_task(self._play_reply(session, reply))
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
                await self._cancel_playback(session, reason="customer-speech")
        else:
            session.barge_in_speech_ms = 0

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
        session.inbound_buffer.clear()
        session.speech_active = False
        session.speech_ms = 0
        session.silence_ms = 0
        if session.customer_speaking:
            session.customer_speaking = False
            await self.realtime_service.publish_speaking_event(session.call_sid, "customer", False)

        if speech_ms < self.settings.stream_vad_min_speech_ms:
            logger.debug("Skipping short utterance for call=%s speech_ms=%s", session.call_sid, speech_ms)
            return

        if silence_detected:
            await self.realtime_service.publish_call_phase(session.call_sid, SILENCE_DETECTED)
        await self.realtime_service.publish_call_phase(session.call_sid, UTTERANCE_FINALIZED)
        await self._enqueue_utterance(session, utterance, speech_ms)

    async def _enqueue_utterance(
        self,
        session: MediaStreamSession,
        mulaw_audio: bytes,
        speech_ms: int,
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
                mulaw_audio=mulaw_audio,
                speech_ms=speech_ms,
                received_at=received_at,
                enqueued_at_perf=perf_counter(),
            )
        )
        logger.info(
            "Latency step=utterance_queued call=%s timestamp=%s speech_ms=%s queue_depth=%s audio_bytes=%s",
            session.call_sid,
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
                await self._process_utterance(session, queued)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Queued utterance processing failed for call=%s", session.call_sid)
            finally:
                queue.task_done()

    async def _process_utterance(self, session: MediaStreamSession, queued: QueuedUtterance) -> None:
        async with session.processing_lock:
            turn_started_at = perf_counter()
            logger.info(
                "Latency step=customer_audio_received call=%s mode=media_stream timestamp=%s audio_bytes=%s",
                session.call_sid,
                queued.received_at,
                len(queued.mulaw_audio),
            )
            emit_latency_event(
                {
                    "step": "customer_audio_received",
                    "call_sid": session.call_sid,
                    "mode": "media_stream",
                    "event_timestamp": queued.received_at,
                    "audio_bytes": len(queued.mulaw_audio),
                    "speech_ms": queued.speech_ms,
                }
            )
            await self.realtime_service.publish_call_phase(session.call_sid, TRANSCRIBING)
            wav_audio = self._mulaw_to_wav(queued.mulaw_audio)
            try:
                stt_result = await asyncio.wait_for(
                    self.stt_service.transcribe(
                        audio_bytes=wav_audio,
                        filename="twilio-stream.wav",
                        content_type="audio/wav",
                        language_code=session.language or "unknown",
                        call_sid=session.call_sid,
                    ),
                    timeout=max(2.0, self.settings.stream_stt_turn_timeout_seconds),
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
                        "audio_bytes": len(queued.mulaw_audio),
                        "timeout_seconds": self.settings.stream_stt_turn_timeout_seconds,
                    }
                )
                stt_result = STTResult(
                    transcript="",
                    language_code=session.language,
                    confidence=0.0,
                    confidence_source="timeout",
                    speech_detected=False,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "STT turn failed for call=%s speech_ms=%s; proceeding with empty transcript. error=%s",
                    session.call_sid,
                    queued.speech_ms,
                    exc,
                )
                emit_latency_event(
                    {
                        "step": "stt_turn_failed",
                        "call_sid": session.call_sid,
                        "event_timestamp": utc_now_iso(),
                        "speech_ms": queued.speech_ms,
                        "audio_bytes": len(queued.mulaw_audio),
                    }
                )
                stt_result = STTResult(
                    transcript="",
                    language_code=session.language,
                    confidence=0.0,
                    confidence_source="error",
                    speech_detected=False,
                )
            transcript = sanitize_spoken_text(stt_result.transcript)

            if transcript and session.playback_task and not session.playback_task.done():
                await self._cancel_playback(session, reason="customer-utterance-finalized")

            async with self.session_factory() as db:
                service = self._build_conversation_service(db)
                reply = await service.handle_live_transcript(
                    call_sid=session.call_sid,
                    transcript=transcript,
                    from_number=session.customer_number,
                    to_number=self.settings.twilio_phone_number,
                    audio_bytes=wav_audio,
                    detected_language=stt_result.language_code,
                    confidence=stt_result.confidence,
                    confidence_source=stt_result.confidence_source,
                    speech_detected=stt_result.speech_detected,
                )

            session.language = reply.language_code
            session.playback_task = asyncio.create_task(self._play_reply(session, reply))
            logger.info(
                "Latency step=assistant_reply_ready call=%s mode=media_stream started_at=%s completed_at=%s total_ms=%s",
                session.call_sid,
                queued.received_at,
                utc_now_iso(),
                int((perf_counter() - turn_started_at) * 1000),
            )
            emit_latency_event(
                {
                    "step": "assistant_reply_ready",
                    "call_sid": session.call_sid,
                    "mode": "media_stream",
                    "started_at": queued.received_at,
                    "completed_at": utc_now_iso(),
                    "latency_ms": int((perf_counter() - turn_started_at) * 1000),
                }
            )

    async def _play_reply(self, session: MediaStreamSession, reply: ConversationReply) -> None:
        if session.closed:
            return

        try:
            session.assistant_playback_started_at = asyncio.get_running_loop().time()
            session.barge_in_speech_ms = 0
            session.playback_started_notified = False
            await self.realtime_service.publish_speaking_event(session.call_sid, "assistant", True)
            streaming_codec = self.tts_service.output_audio_codec
            session.current_tts_codec = streaming_codec
            first_audio_chunk = True
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

            if streaming_codec == "mulaw":
                async for mulaw_audio in self.tts_service.synthesize_chunks(
                    text=reply.text,
                    language_code=reply.language_code,
                    call_sid=session.call_sid,
                    output_audio_codec=streaming_codec,
                    use_cache=False,
                ):
                    if first_audio_chunk:
                        first_audio_chunk = False
                        await self._mark_tts_first_chunk_ready(
                            session,
                            codec=streaming_codec,
                            chunk_bytes=len(mulaw_audio),
                            chunk_kind="mulaw",
                        )
                    await self._send_mulaw_audio(session, mulaw_audio)
            elif streaming_codec == "linear16":
                input_rate = self.tts_service.resolve_sample_rate(streaming_codec)
                pcm_stream = self.tts_service.synthesize_chunks(
                    text=reply.text,
                    language_code=reply.language_code,
                    call_sid=session.call_sid,
                    output_audio_codec=streaming_codec,
                    use_cache=False,
                )

                async def log_first_pcm_chunk(chunk_size: int) -> None:
                    nonlocal first_audio_chunk
                    if not first_audio_chunk:
                        return
                    first_audio_chunk = False
                    await self._mark_tts_first_chunk_ready(
                        session,
                        codec=streaming_codec,
                        chunk_bytes=chunk_size,
                        chunk_kind="pcm",
                    )

                await self._stream_linear16_audio_as_mulaw(
                    session=session,
                    pcm_stream=pcm_stream,
                    input_rate=input_rate,
                    on_first_pcm_chunk=log_first_pcm_chunk,
                )
            else:
                tts_parts: list[bytes] = []
                async for audio_chunk in self.tts_service.synthesize_chunks(
                    text=reply.text,
                    language_code=reply.language_code,
                    call_sid=session.call_sid,
                    output_audio_codec=streaming_codec,
                    use_cache=False,
                ):
                    tts_parts.append(audio_chunk)
                tts_bytes = b"".join(tts_parts)
                if not tts_bytes:
                    raise RuntimeError("Sarvam TTS returned no audio data.")
                await self._mark_tts_first_chunk_ready(
                    session,
                    codec=streaming_codec,
                    chunk_bytes=len(tts_bytes),
                    chunk_kind="provider-audio",
                )
                mulaw_audio = await self._transcode_tts_to_mulaw(tts_bytes)
                await self._send_mulaw_audio(session, mulaw_audio)

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
        finally:
            session.assistant_playback_started_at = None
            session.barge_in_speech_ms = 0
            session.playback_started_notified = False
            session.current_tts_codec = ""
            await self.realtime_service.publish_speaking_event(session.call_sid, "assistant", False)

        if not session.closed and not reply.should_hangup:
            await self.realtime_service.publish_call_phase(session.call_sid, LISTENING)

        if reply.should_hangup:
            await asyncio.sleep(0.5)
            with contextlib.suppress(Exception):
                await asyncio.to_thread(self.twilio_service.end_call, session.call_sid)

    async def _cancel_playback(self, session: MediaStreamSession, reason: str) -> None:
        if not session.playback_task or session.playback_task.done():
            return

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

        session.closed = True
        if session.playback_task and not session.playback_task.done():
            session.playback_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await session.playback_task
        if session.processing_task and not session.processing_task.done():
            session.processing_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await session.processing_task
        if session.customer_speaking:
            await self.realtime_service.publish_speaking_event(session.call_sid, "customer", False)
        await self.realtime_service.publish_speaking_event(session.call_sid, "assistant", False)

    async def _send_json(self, session: MediaStreamSession, payload: dict) -> None:
        async with session.send_lock:
            await session.websocket.send_json(payload)

    async def _send_mulaw_audio(self, session: MediaStreamSession, mulaw_audio: bytes) -> None:
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
        chunk_size = 160
        for index in range(0, len(mulaw_audio), chunk_size):
            if session.closed:
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
            await asyncio.sleep(max(0.01, len(chunk) / 8000))

    async def _stream_linear16_audio_as_mulaw(
        self,
        *,
        session: MediaStreamSession,
        pcm_stream,
        input_rate: int,
        on_first_pcm_chunk,
    ) -> None:
        process = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-loglevel",
            "error",
            "-f",
            "s16le",
            "-ar",
            str(input_rate),
            "-ac",
            "1",
            "-i",
            "pipe:0",
            "-af",
            "highpass=f=120,lowpass=f=3400,acompressor=threshold=-18dB:ratio=2.5:attack=5:release=50,volume=1.5,aresample=resampler=soxr",
            "-ar",
            "8000",
            "-ac",
            "1",
            "-f",
            "mulaw",
            "pipe:1",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        async def writer() -> None:
            assert process.stdin is not None
            try:
                async for pcm_audio in pcm_stream:
                    await on_first_pcm_chunk(len(pcm_audio))
                    process.stdin.write(pcm_audio)
                    await process.stdin.drain()
            finally:
                if process.stdin and not process.stdin.is_closing():
                    process.stdin.close()

        async def reader() -> None:
            assert process.stdout is not None
            while True:
                mulaw_audio = await process.stdout.read(1600)
                if not mulaw_audio:
                    break
                await self._send_mulaw_audio(session, mulaw_audio)

        writer_task = asyncio.create_task(writer())
        reader_task = asyncio.create_task(reader())
        try:
            await asyncio.gather(writer_task, reader_task)
            stderr = b""
            if process.stderr is not None:
                stderr = await process.stderr.read()
            returncode = await process.wait()
            if returncode != 0:
                raise RuntimeError(f"ffmpeg streaming transcoding failed: {stderr.decode('utf-8', 'ignore').strip()}")
        finally:
            if process.returncode is None:
                process.kill()
                with contextlib.suppress(ProcessLookupError):
                    await process.wait()

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
        linear_pcm = audioop.ulaw2lin(mulaw_audio, 2)
        rms = audioop.rms(linear_pcm, 2)
        threshold = self.settings.stream_vad_rms_threshold
        if during_playback:
            # During playback, slightly lower threshold so real user interruption is picked up faster.
            threshold = max(240, int(threshold * 0.85))
        return rms >= threshold

    def _should_cancel_playback(self, session: MediaStreamSession) -> bool:
        if session.assistant_playback_started_at is None:
            return False

        elapsed_ms = int((asyncio.get_running_loop().time() - session.assistant_playback_started_at) * 1000)
        grace_ms = max(0, self.settings.stream_barge_in_grace_ms)
        minimum_playback_ms = max(grace_ms, self.settings.stream_barge_in_min_playback_ms)
        if elapsed_ms < grace_ms:
            return False

        required_speech_ms = max(120, self.settings.stream_barge_in_min_speech_ms)
        strong_speech_ms = max(required_speech_ms + 120, int(required_speech_ms * 1.6))
        if elapsed_ms < minimum_playback_ms and session.barge_in_speech_ms < strong_speech_ms:
            return False

        if session.barge_in_speech_ms < required_speech_ms:
            return False

        if session.speech_ms and session.speech_ms < required_speech_ms:
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

    async def _transcode_tts_to_mulaw(self, audio_bytes: bytes) -> bytes:
        process = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-loglevel",
            "error",
            "-i",
            "pipe:0",
            "-af",
            "highpass=f=180,lowpass=f=3400,volume=1.5",
            "-ar",
            "8000",
            "-ac",
            "1",
            "-f",
            "mulaw",
            "pipe:1",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate(audio_bytes)
        if process.returncode != 0:
            raise RuntimeError(f"ffmpeg transcoding failed: {stderr.decode('utf-8', 'ignore').strip()}")
        return stdout

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
