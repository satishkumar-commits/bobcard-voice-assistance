import logging
import base64
import io
import wave
from dataclasses import dataclass
from time import perf_counter

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


class SarvamSTTService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._streaming_client = (
            AsyncSarvamAI(api_subscription_key=settings.sarvam_api_key)
            if settings.sarvam_api_key and settings.sarvam_stt_use_streaming and AsyncSarvamAI is not None
            else None
        )

    async def transcribe(
        self,
        audio_bytes: bytes,
        filename: str = "caller_audio.wav",
        content_type: str = "audio/wav",
        language_code: str = "unknown",
        call_sid: str = "",
    ) -> STTResult:
        sample_rate = self._extract_sample_rate(audio_bytes, content_type)
        if self._streaming_client and content_type == "audio/wav":
            try:
                payload = await self._transcribe_via_streaming(
                    audio_bytes=audio_bytes,
                    sample_rate=sample_rate,
                    language_code=language_code,
                    call_sid=call_sid,
                )
                return self._build_result(payload, audio_bytes, language_code)
            except Exception as exc:  # pragma: no cover - network/provider fallback
                logger.warning("Sarvam streaming STT failed, falling back to REST: %s", exc)

        payload = await self._transcribe_via_rest(
            audio_bytes=audio_bytes,
            filename=filename,
            content_type=content_type,
            language_code=language_code,
            call_sid=call_sid,
        )
        return self._build_result(payload, audio_bytes, language_code)

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

        async with httpx.AsyncClient(timeout=60.0) as client:
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
                response = await ws.recv()
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
