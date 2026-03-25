import asyncio
import audioop
import contextlib
import logging
import base64
import io
import wave
from collections import deque
from dataclasses import dataclass, field
from time import monotonic, perf_counter
from typing import Any

import httpx

from app.core.issue_guidance import (
    detect_issue_type,
    is_opening_response,
    is_simple_acknowledgement,
    looks_like_repeated_acknowledgement,
    normalize_issue_text,
)
from app.core.config import Settings
from app.services.realtime_service import emit_latency_event
from app.utils.helpers import utc_now_iso

try:
    from sarvamai import AsyncSarvamAI
except ImportError:  # pragma: no cover - fallback when dependency isn't installed yet
    AsyncSarvamAI = None  # type: ignore[assignment]


logger = logging.getLogger(__name__)


@dataclass
class STTResult:
    transcript: str
    language_code: str | None = None
    confidence: float | None = None
    confidence_source: str = "unknown"
    speech_detected: bool | None = None
    raw_response: dict | None = None


@dataclass
class STTChunkStreamSession:
    call_sid: str
    language_code: str
    sample_rate: int
    frame_ms: int
    chunk_ms: int
    preroll_ms: int
    micro_chunk_target_bytes: int
    preroll_frame_capacity: int
    pending_speech: bytearray = field(default_factory=bytearray)
    preroll_frames: deque[bytes] = field(default_factory=deque)
    utterance_chunks: list[bytes] = field(default_factory=list)
    utterance_chunk_count: int = 0
    utterance_audio_bytes: int = 0
    using_speech_run: bool = False
    ws_context: Any | None = None
    ws: Any | None = None
    persistent_stream_active: bool = False
    stream_transport: str = "local-fallback"
    stream_error: str | None = None
    total_streamed_chunks: int = 0
    total_streamed_bytes: int = 0


class SarvamSTTService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._streaming_cooldown_until: dict[str, float] = {}
        self._streaming_failure_count: dict[str, int] = {}
        streaming_enabled = self._is_streaming_enabled_by_mode()
        self._streaming_client = (
            AsyncSarvamAI(api_subscription_key=settings.sarvam_api_key)
            if settings.sarvam_api_key and streaming_enabled and AsyncSarvamAI is not None
            else None
        )

    async def open_stream(
        self,
        *,
        call_sid: str,
        language_code: str = "unknown",
        sample_rate: int = 8000,
        frame_ms: int = 20,
        chunk_ms: int = 200,
        preroll_ms: int = 40,
        enable_persistent: bool = True,
    ) -> STTChunkStreamSession:
        normalized_frame_ms = max(10, int(frame_ms))
        normalized_chunk_ms = max(normalized_frame_ms, int(chunk_ms))
        normalized_preroll_ms = max(0, int(preroll_ms))
        target_bytes = max(1, int(sample_rate * (normalized_chunk_ms / 1000)))
        preroll_capacity = max(0, normalized_preroll_ms // normalized_frame_ms)
        session = STTChunkStreamSession(
            call_sid=call_sid,
            language_code=language_code,
            sample_rate=sample_rate,
            frame_ms=normalized_frame_ms,
            chunk_ms=normalized_chunk_ms,
            preroll_ms=normalized_preroll_ms,
            micro_chunk_target_bytes=target_bytes,
            preroll_frame_capacity=preroll_capacity,
        )
        logger.info(
            "STT chunk stream initialized for call=%s chunk_ms=%s preroll_ms=%s target_bytes=%s",
            call_sid,
            normalized_chunk_ms,
            normalized_preroll_ms,
            target_bytes,
        )
        if not enable_persistent:
            return session
        if not self._is_streaming_enabled_by_mode():
            return session
        if self._streaming_client is None:
            return session
        if not self._can_use_streaming(call_sid):
            return session
        await self._open_persistent_stream_connection(session, reason="initial_connect")
        return session

    async def push_mulaw_frame(
        self,
        session: STTChunkStreamSession,
        *,
        frame: bytes,
        is_speech: bool,
    ) -> None:
        if not frame:
            return

        if is_speech:
            if not session.using_speech_run and session.preroll_frames:
                for preroll_frame in session.preroll_frames:
                    session.pending_speech.extend(preroll_frame)
                session.preroll_frames.clear()
            session.using_speech_run = True
            session.pending_speech.extend(frame)
            await self._flush_pending_chunks(session)
            return

        session.using_speech_run = False
        if session.preroll_frame_capacity <= 0:
            return
        session.preroll_frames.append(frame)
        while len(session.preroll_frames) > session.preroll_frame_capacity:
            session.preroll_frames.popleft()

    async def finalize_utterance_chunks(
        self,
        session: STTChunkStreamSession,
        *,
        language_code: str = "unknown",
    ) -> tuple[bytes, int, STTResult | None, str]:
        if session.pending_speech:
            tail = bytes(session.pending_speech)
            if tail:
                session.utterance_chunks.append(tail)
                session.utterance_chunk_count += 1
                session.utterance_audio_bytes += len(tail)
            session.pending_speech.clear()

        merged = b"".join(session.utterance_chunks) if session.utterance_chunks else b""
        chunk_count = session.utterance_chunk_count
        precomputed_result: STTResult | None = None
        transport = "utterance-fallback"

        if merged and session.persistent_stream_active and session.ws is not None:
            precomputed_result = await self._finalize_stream_utterance(
                session,
                utterance_mulaw=merged,
                language_code=language_code or session.language_code,
            )
            if precomputed_result is not None:
                transport = "persistent-stream"
        self._reset_utterance_buffers(session)
        return merged, chunk_count, precomputed_result, transport

    def discard_utterance_chunks(self, session: STTChunkStreamSession) -> None:
        self._reset_utterance_buffers(session)

    async def close_stream(self, session: STTChunkStreamSession) -> None:
        self._reset_utterance_buffers(session)
        session.preroll_frames.clear()
        await self._disconnect_persistent_stream(session)

    async def _disconnect_persistent_stream(self, session: STTChunkStreamSession) -> None:
        ws = session.ws
        ws_context = session.ws_context
        session.ws = None
        session.ws_context = None
        session.persistent_stream_active = False
        if ws_context is not None:
            with contextlib.suppress(Exception):
                await ws_context.__aexit__(None, None, None)
            return
        if ws is not None and hasattr(ws, "close"):
            with contextlib.suppress(Exception):
                maybe = ws.close()
                if asyncio.iscoroutine(maybe):
                    await maybe

    async def _open_persistent_stream_connection(
        self,
        session: STTChunkStreamSession,
        *,
        reason: str,
    ) -> bool:
        if self._streaming_client is None:
            return False
        if not self._is_streaming_enabled_by_mode():
            return False
        if not self._can_use_streaming(session.call_sid):
            return False

        request_language = session.language_code if session.language_code in {"hi-IN", "en-IN"} else "unknown"
        configured_attempts = max(1, int(self.settings.stt_stream_retry_max))
        max_attempts = configured_attempts
        backoff_seconds = max(0, int(self.settings.stt_stream_backoff_ms)) / 1000
        last_error: Exception | None = None
        last_policy: dict[str, Any] | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                ws_context = self._streaming_client.speech_to_text_streaming.connect(
                    model=self.settings.sarvam_stt_model,
                    mode=self.settings.sarvam_stt_streaming_mode,
                    language_code=request_language,
                    sample_rate=str(session.sample_rate),
                    high_vad_sensitivity="true" if self.settings.sarvam_stt_streaming_high_vad_sensitivity else "false",
                )
                ws = await ws_context.__aenter__()
                session.ws_context = ws_context
                session.ws = ws
                session.persistent_stream_active = True
                session.stream_transport = "sarvam-persistent"
                session.stream_error = None
                self._clear_streaming_failures(session.call_sid)
                step = "stt_persistent_stream_connected" if reason == "initial_connect" else "stt_persistent_stream_reconnected"
                logger.info(
                    "STT persistent stream connected for call=%s language=%s reason=%s attempt=%s",
                    session.call_sid,
                    request_language,
                    reason,
                    attempt,
                )
                emit_latency_event(
                    {
                        "step": step,
                        "call_sid": session.call_sid,
                        "event_timestamp": utc_now_iso(),
                        "language": request_language,
                        "reason": reason,
                        "attempt": attempt,
                    }
                )
                return True
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                error_meta = self._stream_error_meta(exc)
                last_policy = self._stream_recovery_policy(error_meta["error_category"])
                await self._disconnect_persistent_stream(session)
                if last_policy["activate_cooldown"]:
                    self._activate_streaming_cooldown(session.call_sid)
                if not last_policy["retryable"]:
                    break
                max_attempts = min(max_attempts, int(last_policy["max_attempts"]))
                if attempt < max_attempts and backoff_seconds > 0:
                    await asyncio.sleep(backoff_seconds * attempt)

        error_meta = self._stream_error_meta(last_error)
        self._register_streaming_failure(
            session.call_sid,
            error_category=error_meta["error_category"],
        )
        session.stream_error = error_meta["error_type"]
        failure_step = "stt_persistent_stream_failed" if reason == "initial_connect" else "stt_persistent_stream_reconnect_failed"
        logger.warning(
            "STT persistent stream unavailable for call=%s reason=%s attempts=%s error_type=%s error_category=%s detail=%s",
            session.call_sid,
            reason,
            max_attempts,
            error_meta["error_type"],
            error_meta["error_category"],
            error_meta["error_detail"],
        )
        emit_latency_event(
            {
                "step": failure_step,
                "call_sid": session.call_sid,
                "event_timestamp": utc_now_iso(),
                "error_type": error_meta["error_type"],
                "error_category": error_meta["error_category"],
                "error_detail": error_meta["error_detail"],
                "attempts": max_attempts,
                "configured_attempts": configured_attempts,
                "reason": reason,
                "retryable": (last_policy or {}).get("retryable", True),
            }
        )
        return False

    async def _recover_persistent_stream(
        self,
        session: STTChunkStreamSession,
        *,
        reason: str,
        source_error: Exception,
    ) -> tuple[bool, bool]:
        if not session.call_sid or self._streaming_client is None:
            return False, False
        if not self._is_streaming_enabled_by_mode() or not self._can_use_streaming(session.call_sid):
            return False, False

        error_meta = self._stream_error_meta(source_error)
        policy = self._stream_recovery_policy(error_meta["error_category"])
        if policy["activate_cooldown"]:
            self._activate_streaming_cooldown(session.call_sid)
        if not policy["allow_reconnect"]:
            logger.warning(
                "Skipping STT persistent stream recovery for call=%s reason=%s due_to_category=%s",
                session.call_sid,
                reason,
                error_meta["error_category"],
            )
            emit_latency_event(
                {
                    "step": "stt_persistent_stream_reconnect_skipped",
                    "call_sid": session.call_sid,
                    "event_timestamp": utc_now_iso(),
                    "reason": reason,
                    "error_type": error_meta["error_type"],
                    "error_category": error_meta["error_category"],
                    "error_detail": error_meta["error_detail"],
                }
            )
            return False, False
        logger.warning(
            "Attempting STT persistent stream recovery for call=%s reason=%s error_type=%s error_category=%s detail=%s",
            session.call_sid,
            reason,
            error_meta["error_type"],
            error_meta["error_category"],
            error_meta["error_detail"],
        )
        emit_latency_event(
            {
                "step": "stt_persistent_stream_reconnect_requested",
                "call_sid": session.call_sid,
                "event_timestamp": utc_now_iso(),
                "reason": reason,
                "error_type": error_meta["error_type"],
                "error_category": error_meta["error_category"],
                "error_detail": error_meta["error_detail"],
            }
        )
        await self._disconnect_persistent_stream(session)
        recovered = await self._open_persistent_stream_connection(session, reason=reason)
        return True, recovered

    async def _flush_pending_chunks(self, session: STTChunkStreamSession) -> None:
        target_bytes = max(1, session.micro_chunk_target_bytes)
        while len(session.pending_speech) >= target_bytes:
            chunk = bytes(session.pending_speech[:target_bytes])
            del session.pending_speech[:target_bytes]
            session.utterance_chunks.append(chunk)
            session.utterance_chunk_count += 1
            session.utterance_audio_bytes += len(chunk)
            if session.persistent_stream_active and session.ws is not None:
                streamed = await self._stream_chunk_to_persistent(session, chunk)
                if streamed:
                    session.total_streamed_chunks += 1
                    session.total_streamed_bytes += len(chunk)

    async def _stream_chunk_to_persistent(self, session: STTChunkStreamSession, mulaw_chunk: bytes) -> bool:
        wav_chunk = self._mulaw_to_wav(mulaw_chunk)
        audio_b64 = base64.b64encode(wav_chunk).decode("utf-8")
        try:
            if await self._try_ws_transcribe(session, audio_b64):
                return True
            raise RuntimeError("No supported STT streaming send method found")
        except Exception as exc:  # noqa: BLE001
            attempted_recovery, recovered = await self._recover_persistent_stream(
                session,
                reason="chunk_send",
                source_error=exc,
            )
            if recovered:
                try:
                    if await self._try_ws_transcribe(session, audio_b64):
                        return True
                    raise RuntimeError("No supported STT streaming send method found after reconnect")
                except Exception as retry_exc:  # noqa: BLE001
                    await self._deactivate_persistent_stream(session, retry_exc, operation="chunk_send_retry")
                    return False

            if not attempted_recovery:
                await self._deactivate_persistent_stream(session, exc, operation="chunk_send")
            return False

    async def _try_ws_transcribe(self, session: STTChunkStreamSession, audio_b64: str) -> bool:
        ws = session.ws
        if ws is None:
            return False

        if hasattr(ws, "transcribe"):
            try:
                maybe = ws.transcribe(
                    audio=audio_b64,
                    encoding="audio/wav",
                    sample_rate=session.sample_rate,
                )
                if asyncio.iscoroutine(maybe):
                    await maybe
                return True
            except TypeError:
                maybe = ws.transcribe(
                    audio=audio_b64,
                    encoding="audio/wav",
                    sample_rate=str(session.sample_rate),
                )
                if asyncio.iscoroutine(maybe):
                    await maybe
                return True

        payload = {
            "event": "transcribe",
            "audio": audio_b64,
            "encoding": "audio/wav",
            "sample_rate": session.sample_rate,
        }
        if hasattr(ws, "send_json"):
            maybe = ws.send_json(payload)
            if asyncio.iscoroutine(maybe):
                await maybe
            return True
        if hasattr(ws, "send"):
            maybe = ws.send(payload)
            if asyncio.iscoroutine(maybe):
                await maybe
            return True
        return False

    async def _finalize_stream_utterance(
        self,
        session: STTChunkStreamSession,
        *,
        utterance_mulaw: bytes,
        language_code: str,
    ) -> STTResult | None:
        ws = session.ws
        if ws is None:
            return None
        try:
            await self._send_finalize_signal(session)
            max_messages = max(1, int(self.settings.stream_stt_persistent_finalize_max_messages))
            timeout_s = max(0.2, float(self.settings.stream_stt_persistent_finalize_timeout_seconds))
            for _ in range(max_messages):
                payload = await self._recv_payload(session, timeout_s=timeout_s)
                if not payload:
                    continue
                response_type = str(payload.get("type") or "").lower()
                data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
                if response_type == "error":
                    raise RuntimeError(str(data.get("error") or "Unknown persistent STT error"))
                transcript = (
                    data.get("transcript")
                    or data.get("text")
                    or data.get("results", [{}])[0].get("transcript", "")
                )
                if transcript:
                    return self._build_result(data, utterance_mulaw, language_code)
            return None
        except Exception as exc:  # noqa: BLE001
            attempted_recovery, recovered = await self._recover_persistent_stream(
                session,
                reason="finalize_utterance",
                source_error=exc,
            )
            if recovered:
                try:
                    await self._send_finalize_signal(session)
                    max_messages = max(1, int(self.settings.stream_stt_persistent_finalize_max_messages))
                    timeout_s = max(0.2, float(self.settings.stream_stt_persistent_finalize_timeout_seconds))
                    for _ in range(max_messages):
                        payload = await self._recv_payload(session, timeout_s=timeout_s)
                        if not payload:
                            continue
                        response_type = str(payload.get("type") or "").lower()
                        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
                        if response_type == "error":
                            raise RuntimeError(str(data.get("error") or "Unknown persistent STT error"))
                        transcript = (
                            data.get("transcript")
                            or data.get("text")
                            or data.get("results", [{}])[0].get("transcript", "")
                        )
                        if transcript:
                            return self._build_result(data, utterance_mulaw, language_code)
                except Exception as retry_exc:  # noqa: BLE001
                    await self._deactivate_persistent_stream(session, retry_exc, operation="finalize_utterance_retry")
                    return None

            if not attempted_recovery:
                await self._deactivate_persistent_stream(session, exc, operation="finalize_utterance")
            return None

    async def _send_finalize_signal(self, session: STTChunkStreamSession) -> None:
        ws = session.ws
        if ws is None:
            return
        for method_name in ("finish_utterance", "finalize", "end_utterance", "finish", "flush"):
            if hasattr(ws, method_name):
                maybe = getattr(ws, method_name)()
                if asyncio.iscoroutine(maybe):
                    await maybe
                return

        finalize_payloads = (
            {"event": "finish"},
            {"event": "eou"},
            {"type": "finish"},
        )
        if hasattr(ws, "send_json"):
            maybe = ws.send_json(finalize_payloads[0])
            if asyncio.iscoroutine(maybe):
                await maybe
            return
        if hasattr(ws, "send"):
            maybe = ws.send(finalize_payloads[0])
            if asyncio.iscoroutine(maybe):
                await maybe
            return
        raise RuntimeError("No supported finalize method found on persistent STT stream")

    async def _recv_payload(self, session: STTChunkStreamSession, *, timeout_s: float | None = None) -> dict:
        ws = session.ws
        if ws is None:
            return {}
        timeout = timeout_s if timeout_s is not None else self.settings.sarvam_stt_streaming_recv_timeout_seconds
        timeout = max(0.2, float(timeout))
        if hasattr(ws, "recv"):
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
            return self._coerce_streaming_payload(raw)
        if hasattr(ws, "receive"):
            raw = await asyncio.wait_for(ws.receive(), timeout=timeout)
            return self._coerce_streaming_payload(raw)
        if hasattr(ws, "receive_json"):
            raw = await asyncio.wait_for(ws.receive_json(), timeout=timeout)
            return self._coerce_streaming_payload(raw)
        return {}

    async def _deactivate_persistent_stream(
        self,
        session: STTChunkStreamSession,
        exc: Exception,
        *,
        operation: str,
    ) -> None:
        await self._disconnect_persistent_stream(session)
        error_meta = self._stream_error_meta(exc)
        session.stream_error = error_meta["error_type"]
        if session.call_sid:
            self._record_streaming_failure(session.call_sid)
        logger.warning(
            "STT persistent stream deactivated for call=%s operation=%s error_type=%s error_category=%s detail=%s",
            session.call_sid,
            operation,
            error_meta["error_type"],
            error_meta["error_category"],
            error_meta["error_detail"],
        )
        emit_latency_event(
            {
                "step": "stt_persistent_stream_deactivated",
                "call_sid": session.call_sid,
                "event_timestamp": utc_now_iso(),
                "operation": operation,
                "error_type": error_meta["error_type"],
                "error_category": error_meta["error_category"],
                "error_detail": error_meta["error_detail"],
            }
        )

    @staticmethod
    def _reset_utterance_buffers(session: STTChunkStreamSession) -> None:
        session.pending_speech.clear()
        session.utterance_chunks.clear()
        session.utterance_chunk_count = 0
        session.utterance_audio_bytes = 0
        session.using_speech_run = False

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

    async def transcribe(
        self,
        audio_bytes: bytes,
        filename: str = "caller_audio.wav",
        content_type: str = "audio/wav",
        language_code: str = "unknown",
        call_sid: str = "",
    ) -> STTResult:
        sample_rate = self._extract_sample_rate(audio_bytes, content_type)
        streaming_enabled = self._is_streaming_enabled_by_mode()
        streaming_allowed = self._can_use_streaming(call_sid)
        if self._streaming_client and content_type == "audio/wav" and streaming_enabled and streaming_allowed:
            configured_attempts = max(1, int(self.settings.stt_stream_retry_max))
            max_attempts = configured_attempts
            backoff_seconds = max(0, int(self.settings.stt_stream_backoff_ms)) / 1000
            last_error: Exception | None = None
            last_policy: dict[str, Any] | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    payload = await asyncio.wait_for(
                        self._transcribe_via_streaming(
                            audio_bytes=audio_bytes,
                            sample_rate=sample_rate,
                            language_code=language_code,
                            call_sid=call_sid,
                        ),
                        timeout=max(2.0, self.settings.sarvam_stt_streaming_total_timeout_seconds),
                    )
                    self._clear_streaming_failures(call_sid)
                    return self._build_result(payload, audio_bytes, language_code)
                except Exception as exc:  # pragma: no cover - network/provider fallback
                    last_error = exc
                    error_meta = self._stream_error_meta(exc)
                    last_policy = self._stream_recovery_policy(error_meta["error_category"])
                    if last_policy["activate_cooldown"]:
                        self._activate_streaming_cooldown(call_sid)
                    if not last_policy["retryable"]:
                        break
                    max_attempts = min(max_attempts, int(last_policy["max_attempts"]))
                    if attempt < max_attempts and backoff_seconds > 0:
                        await asyncio.sleep(backoff_seconds * attempt)

            error_meta = self._stream_error_meta(last_error)
            self._register_streaming_failure(
                call_sid,
                error_category=error_meta["error_category"],
            )
            logger.warning(
                "Sarvam streaming STT failed after attempts=%s (configured=%s), falling back to REST: error_type=%s error_category=%s retryable=%s detail=%s",
                max_attempts,
                configured_attempts,
                error_meta["error_type"],
                error_meta["error_category"],
                (last_policy or {}).get("retryable", True),
                error_meta["error_detail"],
            )
            emit_latency_event(
                {
                    "step": "sarvam_stt_streaming_fallback",
                    "call_sid": call_sid,
                    "event_timestamp": utc_now_iso(),
                    "error_type": error_meta["error_type"],
                    "error_category": error_meta["error_category"],
                    "error_detail": error_meta["error_detail"],
                    "attempts": max_attempts,
                    "configured_attempts": configured_attempts,
                    "retryable": (last_policy or {}).get("retryable", True),
                }
            )
        elif self._streaming_client and content_type == "audio/wav" and streaming_enabled and not streaming_allowed:
            emit_latency_event(
                {
                    "step": "sarvam_stt_streaming_skipped",
                    "call_sid": call_sid,
                    "event_timestamp": utc_now_iso(),
                    "reason": "cooldown",
                }
            )

        payload = await self._transcribe_via_rest(
            audio_bytes=audio_bytes,
            filename=filename,
            content_type=content_type,
            language_code=language_code,
            call_sid=call_sid,
        )
        return self._build_result(payload, audio_bytes, language_code)

    def _can_use_streaming(self, call_sid: str) -> bool:
        if not self._is_streaming_enabled_by_mode():
            return False
        if not call_sid:
            return True
        cooldown_until = self._streaming_cooldown_until.get(call_sid)
        if cooldown_until is None:
            return True
        if monotonic() >= cooldown_until:
            self._streaming_cooldown_until.pop(call_sid, None)
            return True
        return False

    def _stream_recovery_policy(self, error_category: str) -> dict[str, Any]:
        configured_attempts = max(1, int(self.settings.stt_stream_retry_max))
        policy: dict[str, Any] = {
            "retryable": True,
            "allow_reconnect": True,
            "activate_cooldown": False,
            "max_attempts": configured_attempts,
        }

        if error_category in {"auth", "payload", "protocol", "provider_4xx"}:
            policy.update(
                {
                    "retryable": False,
                    "allow_reconnect": False,
                    "activate_cooldown": True,
                    "max_attempts": 1,
                }
            )
            return policy

        if error_category == "rate_limit":
            policy.update(
                {
                    "retryable": False,
                    "allow_reconnect": False,
                    "activate_cooldown": True,
                    "max_attempts": 1,
                }
            )
            return policy

        if error_category in {"timeout", "empty_response"}:
            policy["max_attempts"] = min(configured_attempts, 2)
            return policy

        if error_category in {"network", "provider_5xx", "provider"}:
            return policy

        return policy

    def _activate_streaming_cooldown(self, call_sid: str) -> None:
        if not call_sid:
            return
        cooldown_seconds = max(1.0, self.settings.sarvam_stt_streaming_cooldown_seconds)
        self._streaming_cooldown_until[call_sid] = monotonic() + cooldown_seconds
        emit_latency_event(
            {
                "step": "sarvam_stt_streaming_cooldown_activated",
                "call_sid": call_sid,
                "event_timestamp": utc_now_iso(),
                "cooldown_seconds": cooldown_seconds,
            }
        )

    def _is_streaming_enabled_by_mode(self) -> bool:
        if self.settings.stt_mode == "rest":
            return False
        if self.settings.stt_mode == "streaming":
            return True
        return self.settings.sarvam_stt_use_streaming

    def _record_streaming_failure(self, call_sid: str) -> None:
        if not call_sid:
            return
        failures = self._streaming_failure_count.get(call_sid, 0) + 1
        self._streaming_failure_count[call_sid] = failures
        breaker_limit = max(1, int(self.settings.stt_stream_cb_fails))
        emit_latency_event(
            {
                "step": "sarvam_stt_streaming_failure",
                "call_sid": call_sid,
                "event_timestamp": utc_now_iso(),
                "failure_count": failures,
                "breaker_limit": breaker_limit,
            }
        )
        if failures >= breaker_limit:
            self._activate_streaming_cooldown(call_sid)
            self._streaming_failure_count.pop(call_sid, None)

    def _register_streaming_failure(self, call_sid: str, *, error_category: str) -> None:
        if error_category in {"auth", "payload", "protocol", "provider_4xx", "rate_limit"}:
            self._activate_streaming_cooldown(call_sid)
            self._streaming_failure_count.pop(call_sid, None)
            emit_latency_event(
                {
                    "step": "sarvam_stt_streaming_failure_hard",
                    "call_sid": call_sid,
                    "event_timestamp": utc_now_iso(),
                    "error_category": error_category,
                }
            )
            return
        self._record_streaming_failure(call_sid)

    def _clear_streaming_failures(self, call_sid: str) -> None:
        if not call_sid:
            return
        self._streaming_failure_count.pop(call_sid, None)

    @staticmethod
    def _stream_error_meta(exc: Exception | None) -> dict[str, str]:
        if exc is None:
            return {
                "error_type": "UnknownError",
                "error_category": "unknown",
                "error_detail": "No error details available",
            }

        error_type = type(exc).__name__
        message = " ".join(str(exc).strip().split())
        if len(message) > 180:
            message = f"{message[:177]}..."
        if not message:
            message = "No error details available"

        if isinstance(exc, (asyncio.TimeoutError, TimeoutError, httpx.TimeoutException)):
            category = "timeout"
        elif isinstance(exc, httpx.HTTPStatusError):
            status_code = exc.response.status_code if exc.response is not None else 0
            if status_code in {401, 403}:
                category = "auth"
            elif status_code == 429:
                category = "rate_limit"
            elif 500 <= status_code <= 599:
                category = "provider_5xx"
            else:
                category = "provider_4xx"
        elif isinstance(exc, (httpx.TransportError, OSError, ConnectionError)):
            category = "network"
        elif isinstance(exc, (TypeError, ValueError, KeyError)):
            category = "payload"
        else:
            lower_message = message.lower()
            if "no transcript" in lower_message:
                category = "empty_response"
            elif "unsupported" in lower_message or "no supported" in lower_message:
                category = "protocol"
            elif "rate limit" in lower_message:
                category = "rate_limit"
            else:
                category = "provider"

        return {
            "error_type": error_type,
            "error_category": category,
            "error_detail": message,
        }

    async def _transcribe_via_rest(
        self,
        *,
        audio_bytes: bytes,
        filename: str,
        content_type: str,
        language_code: str,
        call_sid: str,
    ) -> dict:
        headers = {"api-subscription-key": self.settings.sarvam_api_key}
        data = {
            "model": self.settings.sarvam_stt_model,
            "language_code": language_code,
        }
        files = {"file": (filename, audio_bytes, content_type)}

        async with httpx.AsyncClient(timeout=max(2.0, self.settings.sarvam_stt_rest_timeout_seconds)) as client:
            request_sent_at = utc_now_iso()
            started_at = perf_counter()
            response = await client.post(
                f"{self.settings.sarvam_base_url}/speech-to-text",
                headers=headers,
                data=data,
                files=files,
            )
            response.raise_for_status()
            logger.info(
                "Latency step=sarvam_stt call=%s request_sent_at=%s response_received_at=%s latency_ms=%s language=%s transport=rest",
                call_sid or "unknown",
                request_sent_at,
                utc_now_iso(),
                int((perf_counter() - started_at) * 1000),
                language_code,
            )
            emit_latency_event(
                {
                    "step": "sarvam_stt",
                    "call_sid": call_sid,
                    "request_sent_at": request_sent_at,
                    "response_received_at": utc_now_iso(),
                    "latency_ms": int((perf_counter() - started_at) * 1000),
                    "language": language_code,
                    "transport": "rest",
                }
            )
            return response.json()

    async def _transcribe_via_streaming(
        self,
        *,
        audio_bytes: bytes,
        sample_rate: int,
        language_code: str,
        call_sid: str,
    ) -> dict:
        if self._streaming_client is None:
            raise RuntimeError("Sarvam streaming STT client is not available")

        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
        request_language = language_code if language_code in {"hi-IN", "en-IN"} else "unknown"
        request_sent_at = utc_now_iso()
        started_at = perf_counter()
        async with self._streaming_client.speech_to_text_streaming.connect(
            model=self.settings.sarvam_stt_model,
            mode=self.settings.sarvam_stt_streaming_mode,
            language_code=request_language,
            sample_rate=str(sample_rate),
            high_vad_sensitivity="true" if self.settings.sarvam_stt_streaming_high_vad_sensitivity else "false",
        ) as ws:
            await ws.transcribe(
                audio=audio_b64,
                encoding="audio/wav",
                sample_rate=sample_rate,
            )

            for _ in range(4):
                response = await asyncio.wait_for(
                    ws.recv(),
                    timeout=max(1.0, self.settings.sarvam_stt_streaming_recv_timeout_seconds),
                )
                payload = self._coerce_streaming_payload(response)
                response_type = payload.get("type")
                data = payload.get("data") if isinstance(payload.get("data"), dict) else {}

                if response_type == "error":
                    raise RuntimeError(data.get("error") or "Unknown Sarvam STT streaming error")
                if response_type == "data" and data.get("transcript"):
                    logger.info(
                        "Latency step=sarvam_stt call=%s request_sent_at=%s response_received_at=%s latency_ms=%s language=%s transport=streaming",
                        call_sid or "unknown",
                        request_sent_at,
                        utc_now_iso(),
                        int((perf_counter() - started_at) * 1000),
                        request_language,
                    )
                    emit_latency_event(
                        {
                            "step": "sarvam_stt",
                            "call_sid": call_sid,
                            "request_sent_at": request_sent_at,
                            "response_received_at": utc_now_iso(),
                            "latency_ms": int((perf_counter() - started_at) * 1000),
                            "language": request_language,
                            "transport": "streaming",
                        }
                    )
                    return data

            raise RuntimeError("Sarvam STT streaming returned no transcript")

    def _build_result(self, payload: dict, audio_bytes: bytes, language_code: str) -> STTResult:
        transcript = (
            payload.get("transcript")
            or payload.get("text")
            or payload.get("results", [{}])[0].get("transcript", "")
        )
        detected_language = payload.get("language_code") or payload.get("language")
        transcript = self._normalize_transcript(transcript, detected_language or language_code)
        confidence, confidence_source = self._extract_confidence(payload, transcript)
        speech_detected = bool(transcript.strip()) or len(audio_bytes) >= self.settings.vad_min_audio_bytes
        logger.info("Sarvam STT transcript generated with language=%s", detected_language)
        return STTResult(
            transcript=transcript.strip(),
            language_code=detected_language,
            confidence=confidence,
            confidence_source=confidence_source,
            speech_detected=speech_detected,
            raw_response=payload,
        )

    @staticmethod
    def _coerce_streaming_payload(response: object) -> dict:
        if hasattr(response, "model_dump"):
            return response.model_dump()  # type: ignore[no-any-return]
        if hasattr(response, "dict"):
            return response.dict()  # type: ignore[no-any-return]
        if isinstance(response, dict):
            return response
        return {}

    @staticmethod
    def _extract_sample_rate(audio_bytes: bytes, content_type: str) -> int:
        if content_type != "audio/wav":
            return 16000
        try:
            with wave.open(io.BytesIO(audio_bytes), "rb") as wav_file:
                return wav_file.getframerate() or 16000
        except wave.Error:
            return 16000

    def _extract_confidence(self, payload: dict, transcript: str) -> tuple[float | None, str]:
        heuristic_confidence: float | None = None
        heuristic_source = "heuristic"
        normalized = normalize_issue_text(transcript)
        if is_opening_response(transcript):
            heuristic_confidence, heuristic_source = 0.82, "heuristic-opening"
        elif is_simple_acknowledgement(transcript):
            heuristic_confidence, heuristic_source = 0.78, "heuristic-choice"
        elif looks_like_repeated_acknowledgement(transcript):
            heuristic_confidence, heuristic_source = 0.72, "heuristic-repeated-choice"
        elif normalized in {"callback", "call back", "send link", "sms", "yes", "no"}:
            heuristic_confidence, heuristic_source = 0.78, "heuristic-choice"
        elif detect_issue_type(transcript):
            heuristic_confidence, heuristic_source = 0.68, "heuristic-issue"

        candidates = [
            payload.get("confidence"),
            payload.get("average_confidence"),
            payload.get("transcript_confidence"),
        ]

        first_result = payload.get("results", [{}])[0] if isinstance(payload.get("results"), list) else {}
        if isinstance(first_result, dict):
            candidates.extend(
                [
                    first_result.get("confidence"),
                    first_result.get("average_confidence"),
                ]
            )

        for item in candidates:
            if isinstance(item, (int, float)):
                provider_confidence = max(0.0, min(float(item), 1.0))
                if heuristic_confidence is not None and provider_confidence < heuristic_confidence:
                    return heuristic_confidence, heuristic_source
                return provider_confidence, "provider"

        if heuristic_confidence is not None:
            return heuristic_confidence, heuristic_source

        if not transcript.strip():
            return 0.0, "heuristic"

        words = transcript.split()
        alpha_chars = sum(char.isalpha() for char in transcript)
        total_chars = len(transcript) or 1
        alpha_ratio = alpha_chars / total_chars

        score = 0.2
        if len(words) >= 2:
            score += 0.25
        if len(transcript.strip()) >= 8:
            score += 0.2
        if alpha_ratio >= 0.6:
            score += 0.15
        if len(words) >= 4:
            score += 0.1

        return min(score, 0.85), "heuristic"

    @staticmethod
    def _normalize_transcript(transcript: str, language_code: str | None) -> str:
        cleaned = " ".join((transcript or "").strip().split())
        if not cleaned:
            return ""

        replacements = {
            "aadhar": "aadhaar",
            "adhar": "aadhaar",
            "e statement": "statement",
            "e-statement": "statement",
            "log in": "login",
            "sign in": "login",
            "otc": "otp",
            "ओटीसी": "ओटीपी",
        }
        normalized = cleaned
        for source, target in replacements.items():
            normalized = normalized.replace(source, target).replace(source.title(), target.title())

        if language_code == "hi-IN":
            normalized = normalized.replace(" ओ टी पी ", " ओटीपी ")
            normalized = normalized.replace(" ई एम आई ", " ईएमआई ")
        return normalized
