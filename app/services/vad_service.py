from dataclasses import dataclass
from datetime import UTC, datetime

from app.core.config import Settings


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class VADDecision:
    speech_detected: bool
    speech_started: bool
    speech_stopped: bool
    silence_detected: bool
    likely_noise_only: bool
    reason: str


@dataclass
class VADState:
    call_sid: str
    last_speech_at: datetime | None = None
    speech_active: bool = False
    consecutive_silence_count: int = 0


class VADService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._states: dict[str, VADState] = {}

    def get_state(self, call_sid: str) -> VADState:
        if call_sid not in self._states:
            self._states[call_sid] = VADState(call_sid=call_sid)
        return self._states[call_sid]

    def evaluate_turn(
        self,
        *,
        call_sid: str,
        audio_bytes: bytes | None,
        transcript: str,
        provider_speech_detected: bool | None = None,
    ) -> tuple[VADState, VADDecision]:
        state = self.get_state(call_sid)
        audio_length = len(audio_bytes or b"")
        transcript_present = bool(transcript.strip())
        speech_detected = provider_speech_detected if provider_speech_detected is not None else (
            transcript_present or audio_length >= self.settings.vad_min_audio_bytes
        )
        likely_noise_only = audio_length >= self.settings.vad_min_audio_bytes and not transcript_present
        silence_detected = not speech_detected
        speech_started = speech_detected and not state.speech_active
        speech_stopped = silence_detected and state.speech_active

        if speech_detected:
            state.last_speech_at = utc_now()
            state.speech_active = True
            state.consecutive_silence_count = 0
            reason = "speech-detected"
        else:
            state.speech_active = False
            state.consecutive_silence_count += 1
            reason = "silence-detected"

        if likely_noise_only:
            reason = "noise-only-audio"

        return state, VADDecision(
            speech_detected=speech_detected,
            speech_started=speech_started,
            speech_stopped=speech_stopped,
            silence_detected=silence_detected,
            likely_noise_only=likely_noise_only,
            reason=reason,
        )


_vad_service: VADService | None = None


def get_vad_service(settings: Settings) -> VADService:
    global _vad_service
    if _vad_service is None:
        _vad_service = VADService(settings)
    return _vad_service
