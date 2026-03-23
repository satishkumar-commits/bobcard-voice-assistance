import asyncio
import base64
import json
import logging
from collections.abc import AsyncIterator
from collections import OrderedDict
from pathlib import Path
from time import perf_counter

import httpx

from app.core.config import Settings
from app.services.realtime_service import emit_latency_event
from app.utils.helpers import ensure_directory, generate_audio_filename, utc_now_iso

try:
    from sarvamai import AsyncSarvamAI, AudioOutput
except ImportError:  # pragma: no cover - fallback when dependency isn't installed yet
    AsyncSarvamAI = None  # type: ignore[assignment]
    AudioOutput = None  # type: ignore[assignment]


logger = logging.getLogger(__name__)

_TTS_STREAM_FINAL_TYPES = {"complete", "completed", "completion", "done", "final", "finished"}
_TTS_STREAM_ERROR_TYPES = {"error", "failed", "failure"}
_TTS_STREAM_INITIAL_TIMEOUT_S = 8.0
_TTS_STREAM_IDLE_TIMEOUT_S = 2.5


class SarvamTTSService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._cache: OrderedDict[tuple[str, str, str], bytes] = OrderedDict()
        self._http_client = httpx.AsyncClient(timeout=60.0)
        self._streaming_client = (
            AsyncSarvamAI(api_subscription_key=settings.sarvam_api_key)
            if settings.sarvam_api_key and settings.sarvam_tts_use_streaming and AsyncSarvamAI is not None
            else None
        )

    @property
    def output_audio_codec(self) -> str:
        return self.settings.sarvam_tts_output_audio_codec.strip().lower() or "mulaw"

    def resolve_sample_rate(self, output_audio_codec: str | None = None) -> int:
        codec = (output_audio_codec or self.output_audio_codec).strip().lower() or self.output_audio_codec
        return self._effective_sample_rate(codec)

    async def synthesize_chunks(
        self,
        text: str,
        language_code: str,
        call_sid: str = "",
        output_audio_codec: str | None = None,
        use_cache: bool = True,
    ) -> AsyncIterator[bytes]:
        prepared_text = self._prepare_text_for_tts(text, language_code)
        resolved_codec = (output_audio_codec or self.output_audio_codec).strip().lower() or self.output_audio_codec
        cache_key = (language_code, prepared_text, resolved_codec)
        if use_cache:
            cached_audio = self._cache_get(cache_key)
            if cached_audio is not None:
                logger.info(
                    "Latency step=sarvam_tts_cache call=%s timestamp=%s language=%s text_preview=%s",
                    call_sid or "unknown",
                    utc_now_iso(),
                    language_code,
                    prepared_text[:80],
                )
                emit_latency_event(
                    {
                        "step": "sarvam_tts_cache",
                        "call_sid": call_sid,
                        "event_timestamp": utc_now_iso(),
                        "language": language_code,
                        "text_preview": prepared_text[:80],
                    }
                )
                yield cached_audio
                return

        if self._streaming_client is not None:
            streamed_audio = bytearray()
            try:
                async for chunk in self._stream_via_websocket(
                    prepared_text=prepared_text,
                    language_code=language_code,
                    call_sid=call_sid,
                    output_audio_codec=resolved_codec,
                ):
                    streamed_audio.extend(chunk)
                    yield chunk
                if streamed_audio:
                    if use_cache:
                        self._cache_put(cache_key, bytes(streamed_audio))
                    return
            except Exception as exc:  # pragma: no cover - provider fallback
                if streamed_audio:
                    logger.exception("Sarvam streaming TTS failed after audio had already started for call=%s", call_sid)
                    raise
                logger.warning("Sarvam streaming TTS failed, falling back to REST: %s", exc)

        audio_bytes = await self._synthesize_via_rest(
            prepared_text=prepared_text,
            language_code=language_code,
            call_sid=call_sid,
            output_audio_codec=resolved_codec,
        )
        if use_cache:
            self._cache_put(cache_key, audio_bytes)
        yield audio_bytes

    async def synthesize_bytes(
        self,
        text: str,
        language_code: str,
        call_sid: str = "",
        output_audio_codec: str | None = None,
        use_cache: bool = True,
    ) -> bytes:
        chunks: list[bytes] = []
        async for chunk in self.synthesize_chunks(
            text=text,
            language_code=language_code,
            call_sid=call_sid,
            output_audio_codec=output_audio_codec,
            use_cache=use_cache,
        ):
            chunks.append(chunk)
        return b"".join(chunks)

    async def synthesize(self, text: str, language_code: str, call_sid: str) -> Path:
        audio_bytes = await self.synthesize_bytes(
            text=text,
            language_code=language_code,
            call_sid=call_sid,
            output_audio_codec="mp3",
            use_cache=True,
        )
        output_path = self.settings.generated_audio_path / generate_audio_filename(call_sid)
        ensure_directory(output_path.parent)
        output_path.write_bytes(audio_bytes)
        self._schedule_cleanup(output_path)
        logger.info("Sarvam TTS audio saved to %s", output_path)
        return output_path

    def _build_payload(
        self,
        prepared_text: str,
        language_code: str,
        output_audio_codec: str,
    ) -> dict[str, str | int | float | bool]:
        payload: dict[str, str | int | float | bool] = {
            "text": prepared_text,
            "target_language_code": language_code,
            "speaker": self._normalized_speaker(self.settings.sarvam_tts_voice),
            "model": self.settings.sarvam_tts_model,
            "pace": self._effective_pace(language_code),
            "speech_sample_rate": self._effective_sample_rate(output_audio_codec),
            "enable_preprocessing": self.settings.sarvam_tts_enable_preprocessing,
            "output_audio_codec": output_audio_codec,
        }
        return payload

    async def _synthesize_via_rest(
        self,
        *,
        prepared_text: str,
        language_code: str,
        call_sid: str,
        output_audio_codec: str,
    ) -> bytes:
        headers = {"api-subscription-key": self.settings.sarvam_api_key}
        payload = self._build_payload(
            prepared_text=prepared_text,
            language_code=language_code,
            output_audio_codec=output_audio_codec,
        )

        started_at = perf_counter()
        request_sent_at = utc_now_iso()
        response = await self._http_client.post(
            f"{self.settings.sarvam_base_url}/text-to-speech",
            headers=headers,
            json=payload,
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            error_detail = self._extract_error_detail(response)
            logger.error(
                "Sarvam TTS request failed status=%s model=%s speaker=%s detail=%s",
                response.status_code,
                payload.get("model"),
                payload.get("speaker"),
                error_detail,
            )
            raise RuntimeError(f"Sarvam TTS request failed: {error_detail}") from exc

        data = response.json()
        audio_items = data.get("audios") or []
        if not audio_items:
            raise ValueError("Sarvam TTS returned no audio data.")

        audio_bytes = base64.b64decode(audio_items[0])
        response_received_at = utc_now_iso()
        latency_ms = int((perf_counter() - started_at) * 1000)
        logger.info(
            "Latency step=sarvam_tts call=%s request_sent_at=%s response_received_at=%s latency_ms=%s language=%s transport=rest text_preview=%s",
            call_sid or "unknown",
            request_sent_at,
            response_received_at,
            latency_ms,
            language_code,
            prepared_text[:80],
        )
        emit_latency_event(
            {
                "step": "sarvam_tts",
                "call_sid": call_sid,
                "request_sent_at": request_sent_at,
                "response_received_at": response_received_at,
                "latency_ms": latency_ms,
                "language": language_code,
                "transport": "rest",
                "codec": output_audio_codec,
                "text_preview": prepared_text[:80],
            }
        )
        return audio_bytes

    async def _stream_via_websocket(
        self,
        *,
        prepared_text: str,
        language_code: str,
        call_sid: str,
        output_audio_codec: str,
    ) -> AsyncIterator[bytes]:
        if self._streaming_client is None:
            raise RuntimeError("Sarvam streaming TTS client is not available")

        request_sent_at = utc_now_iso()
        started_at = perf_counter()
        first_chunk_sent = False
        total_audio_bytes = 0
        saw_completion_event = False
        async with self._open_streaming_tts_connection() as ws:
            await ws.configure(
                target_language_code=language_code,
                speaker=self._normalized_speaker(self.settings.sarvam_tts_voice),
                pace=self._effective_pace(language_code),
                min_buffer_size=self.settings.sarvam_tts_streaming_min_buffer_size,
                max_chunk_length=self.settings.sarvam_tts_streaming_max_chunk_length,
                output_audio_codec=output_audio_codec,
                output_audio_bitrate=self.settings.sarvam_tts_output_audio_bitrate,
            )
            await ws.convert(prepared_text)
            await ws.flush()

            stream_iterator = ws.__aiter__()
            while True:
                timeout_s = _TTS_STREAM_IDLE_TIMEOUT_S if first_chunk_sent else _TTS_STREAM_INITIAL_TIMEOUT_S
                try:
                    message = await asyncio.wait_for(anext(stream_iterator), timeout=timeout_s)
                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError:
                    if total_audio_bytes > 0:
                        logger.warning(
                            "Sarvam TTS stream timed out waiting for completion; closing reply early call=%s codec=%s audio_bytes=%s",
                            call_sid or "unknown",
                            output_audio_codec,
                            total_audio_bytes,
                        )
                        break
                    raise RuntimeError("Sarvam TTS streaming timed out before any audio was received")

                audio_chunk = self._extract_stream_audio_chunk(message)
                if audio_chunk:
                    total_audio_bytes += len(audio_chunk)
                    if not first_chunk_sent:
                        first_chunk_sent = True
                        first_response_at = utc_now_iso()
                        first_chunk_latency_ms = int((perf_counter() - started_at) * 1000)
                        logger.info(
                            "Latency step=sarvam_tts_first_chunk call=%s request_sent_at=%s first_chunk_at=%s latency_ms=%s language=%s codec=%s chunk_bytes=%s",
                            call_sid or "unknown",
                            request_sent_at,
                            first_response_at,
                            first_chunk_latency_ms,
                            language_code,
                            output_audio_codec,
                            len(audio_chunk),
                        )
                        emit_latency_event(
                            {
                                "step": "sarvam_tts_first_chunk",
                                "call_sid": call_sid,
                                "request_sent_at": request_sent_at,
                                "response_received_at": first_response_at,
                                "latency_ms": first_chunk_latency_ms,
                                "language": language_code,
                                "transport": "streaming",
                                "codec": output_audio_codec,
                                "chunk_bytes": len(audio_chunk),
                            }
                        )
                    yield audio_chunk
                    continue

                error_detail = self._extract_stream_error_detail(message)
                if error_detail:
                    raise RuntimeError(f"Sarvam TTS streaming error: {error_detail}")

                if self._is_stream_completion_message(message):
                    saw_completion_event = True
                    break

        if total_audio_bytes <= 0:
            raise RuntimeError("Sarvam TTS streaming returned no audio chunks")

        completed_at = utc_now_iso()
        total_latency_ms = int((perf_counter() - started_at) * 1000)
        logger.info(
            "Latency step=sarvam_tts call=%s request_sent_at=%s response_received_at=%s latency_ms=%s language=%s transport=streaming codec=%s audio_bytes=%s text_preview=%s",
            call_sid or "unknown",
            request_sent_at,
            completed_at,
            total_latency_ms,
            language_code,
            output_audio_codec,
            total_audio_bytes,
            prepared_text[:80],
        )
        emit_latency_event(
            {
                "step": "sarvam_tts",
                "call_sid": call_sid,
                "request_sent_at": request_sent_at,
                "response_received_at": completed_at,
                "latency_ms": total_latency_ms,
                "language": language_code,
                "transport": "streaming",
                "codec": output_audio_codec,
                "audio_bytes": total_audio_bytes,
                "text_preview": prepared_text[:80],
            }
        )
        if saw_completion_event:
            logger.debug("Sarvam TTS streaming completion event received for call=%s", call_sid or "unknown")

    def _open_streaming_tts_connection(self):
        connect = self._streaming_client.text_to_speech_streaming.connect
        try:
            return connect(
                model=self.settings.sarvam_tts_model,
                send_completion_event=True,
            )
        except TypeError:
            return connect(model=self.settings.sarvam_tts_model)

    @staticmethod
    def _normalized_speaker(speaker: str) -> str:
        return speaker.strip().lower()

    def _effective_pace(self, language_code: str) -> float:
        base_pace = float(self.settings.sarvam_tts_pace)
        if language_code == "hi-IN":
            return max(0.96, min(base_pace, 1.05))
        return base_pace

    def _effective_sample_rate(self, output_audio_codec: str) -> int:
        if output_audio_codec in {"mulaw", "alaw"}:
            return 8000
        if output_audio_codec == "linear16":
            return int(self.settings.sarvam_tts_sample_rate)
        return int(self.settings.sarvam_tts_sample_rate)

    @staticmethod
    def _prepare_text_for_tts(text: str, language_code: str) -> str:
        cleaned = " ".join((text or "").strip().split())
        cleaned = cleaned.replace("। ", "। ").replace("? ", "? ").replace("! ", "! ")
        if language_code != "hi-IN":
            replacements = {
                "BOBCards": "BOB Cards",
                "bobcards": "BOB Cards",
                "OTP": "O T P",
                "EMI": "E M I",
                "KYC": "K Y C",
                "PAN": "P A N",
                "PDF": "P D F",
                "BOB": "B O B",
            }
            normalized = cleaned
            for source, target in replacements.items():
                normalized = normalized.replace(source, target)
            return normalized

        replacements = {
            "OTP": "ओटीपी",
            "EMI": "ईएमआई",
            "SMS": "एसएमएस",
            "app": "ऐप",
            "App": "ऐप",
            "step by step": "एक एक कदम में",
            "Step by step": "एक एक कदम में",
            "credit card": "क्रेडिट कार्ड",
            "Credit card": "क्रेडिट कार्ड",
            "banking process": "बैंकिंग प्रक्रिया",
            "Banking process": "बैंकिंग प्रक्रिया",
            "resend": "फिर से भेजें",
            "Resend": "फिर से भेजें",
            "inbox": "इनबॉक्स",
            "Inbox": "इनबॉक्स",
            "password": "पासवर्ड",
            "Password": "पासवर्ड",
            "error message": "एरर मैसेज",
            "Error message": "एरर मैसेज",
            "error": "एरर",
            "Error": "एरर",
            "download": "डाउनलोड",
            "Download": "डाउनलोड",
            "upload": "अपलोड",
            "Upload": "अपलोड",
            "request": "रिक्वेस्ट",
            "Request": "रिक्वेस्ट",
            "section": "सेक्शन",
            "Section": "सेक्शन",
            "option": "ऑप्शन",
            "Option": "ऑप्शन",
            "visible": "विज़िबल",
            "Visible": "विज़िबल",
            "sign in": "साइन इन",
            "Sign in": "साइन इन",
            "reset": "रीसेट",
            "Reset": "रीसेट",
            "reference": "रेफरेंस",
            "Reference": "रेफरेंस",
            "details": "डिटेल्स",
            "Details": "डिटेल्स",
            "documents": "डॉक्यूमेंट्स",
            "Documents": "डॉक्यूमेंट्स",
            "check": "जाँचिए",
            "Check": "जाँचिए",
            "verify": "सत्यापित कीजिए",
            "Verify": "सत्यापित कीजिए",
            "statement": "स्टेटमेंट",
            "Statement": "स्टेटमेंट",
            "refund": "रिफंड",
            "Refund": "रिफंड",
            "invoice": "इनवॉइस",
            "Invoice": "इनवॉइस",
            "BOBCards": "बॉब कार्ड्स",
            "bobcards": "बॉब कार्ड्स",
            "BOB Cards": "बॉब कार्ड्स",
            "BOB Card": "बॉब कार्ड",
            "credit card": "क्रेडिट कार्ड",
            "Credit card": "क्रेडिट कार्ड",
            "credit Card": "क्रेडिट कार्ड",
            "Aadhaar": "आधार",
            "aadhaar": "आधार",
            "PAN": "पैन",
            "KYC": "के वाई सी",
            "PDF": "पी डी एफ",
            "login": "लॉगिन",
            "Login": "लॉगिन",
            "portal": "पोर्टल",
            "Portal": "पोर्टल",
        }
        normalized = cleaned
        for source, target in replacements.items():
            normalized = normalized.replace(source, target)
        return normalized

    def _cache_get(self, cache_key: tuple[str, str, str]) -> bytes | None:
        cached_audio = self._cache.get(cache_key)
        if cached_audio is None:
            return None
        self._cache.move_to_end(cache_key)
        return cached_audio

    def _cache_put(self, cache_key: tuple[str, str, str], audio_bytes: bytes) -> None:
        if len(cache_key[1]) > 220:
            return
        self._cache[cache_key] = audio_bytes
        self._cache.move_to_end(cache_key)
        while len(self._cache) > self.settings.tts_cache_max_entries:
            self._cache.popitem(last=False)

    def _schedule_cleanup(self, output_path: Path) -> None:
        ttl = max(15, int(self.settings.generated_audio_ttl_seconds))

        async def cleanup_file() -> None:
            await asyncio.sleep(ttl)
            try:
                output_path.unlink(missing_ok=True)
                logger.info("Generated audio deleted from %s", output_path)
            except OSError as exc:
                logger.warning("Failed to delete generated audio %s: %s", output_path, exc)

        try:
            asyncio.get_running_loop().create_task(cleanup_file())
        except RuntimeError:
            logger.debug("No running event loop to schedule cleanup for %s", output_path)

    @staticmethod
    def _extract_error_detail(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except json.JSONDecodeError:
            return response.text.strip() or f"HTTP {response.status_code}"

        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                message = error.get("message")
                code = error.get("code")
                if message and code:
                    return f"{code}: {message}"
                if message:
                    return str(message)
            detail = payload.get("detail")
            if detail:
                return str(detail)

        return response.text.strip() or f"HTTP {response.status_code}"

    @staticmethod
    def _extract_stream_audio_chunk(message: object) -> bytes | None:
        if AudioOutput is not None and isinstance(message, AudioOutput):
            data = getattr(message, "data", None)
            audio_b64 = getattr(data, "audio", None)
            if isinstance(audio_b64, str) and audio_b64:
                return base64.b64decode(audio_b64)

        payload = SarvamTTSService._coerce_streaming_payload(message)
        if not payload:
            return None

        data = payload.get("data")
        if isinstance(data, dict):
            audio_b64 = data.get("audio")
            if isinstance(audio_b64, str) and audio_b64:
                return base64.b64decode(audio_b64)

        audio_b64 = payload.get("audio")
        if isinstance(audio_b64, str) and audio_b64:
            return base64.b64decode(audio_b64)
        return None

    @staticmethod
    def _is_stream_completion_message(message: object) -> bool:
        payload = SarvamTTSService._coerce_streaming_payload(message)
        if not payload:
            return False

        payload_type = str(payload.get("type", "")).strip().lower()
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        event_type = str(
            data.get("event_type")
            or payload.get("event_type")
            or data.get("event")
            or payload.get("event")
            or data.get("type")
            or ""
        ).strip().lower()
        status = str(data.get("status") or payload.get("status") or "").strip().lower()
        return (
            payload_type in _TTS_STREAM_FINAL_TYPES
            or event_type in _TTS_STREAM_FINAL_TYPES
            or status in _TTS_STREAM_FINAL_TYPES
        )

    @staticmethod
    def _extract_stream_error_detail(message: object) -> str | None:
        payload = SarvamTTSService._coerce_streaming_payload(message)
        if not payload:
            return None

        payload_type = str(payload.get("type", "")).strip().lower()
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        event_type = str(data.get("event_type") or payload.get("event_type") or "").strip().lower()
        if payload_type not in _TTS_STREAM_ERROR_TYPES and event_type not in _TTS_STREAM_ERROR_TYPES:
            return None

        for candidate in (
            data.get("error"),
            payload.get("error"),
            data.get("message"),
            payload.get("message"),
            data.get("detail"),
            payload.get("detail"),
        ):
            if candidate:
                return str(candidate)
        return "unknown streaming error"

    @staticmethod
    def _coerce_streaming_payload(response: object) -> dict:
        if hasattr(response, "model_dump"):
            return response.model_dump()  # type: ignore[no-any-return]
        if hasattr(response, "dict"):
            return response.dict()  # type: ignore[no-any-return]
        if isinstance(response, dict):
            return response
        return {}
