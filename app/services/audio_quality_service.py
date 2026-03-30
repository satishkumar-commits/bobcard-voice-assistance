from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from app.core.config import Settings
from app.core.conversation_prompts import is_short_valid_intent


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class AudioQualityAssessment:
    transcript_reliable: bool
    likely_noisy: bool
    retry_recommended: bool
    fallback_recommended: bool
    speech_detected: bool
    confidence: float
    confidence_source: str
    reason: str
    quality_label: str


@dataclass
class CallAudioState:
    call_sid: str
    retry_count: int = 0
    low_confidence_count: int = 0
    empty_input_count: int = 0
    consecutive_unclear_count: int = 0
    noise_flag: bool = False
    fallback_mode: bool = False
    short_response_mode: bool = False
    last_good_transcript_at: datetime | None = None
    last_confidence: float = 0.0
    last_confidence_source: str = "unknown"
    last_reason: str = "new-call"
    last_quality_label: str = "clear"
    last_intent: str | None = None

    def as_payload(self) -> dict[str, str | int | float | bool | None]:
        payload = asdict(self)
        if self.last_good_transcript_at:
            payload["last_good_transcript_at"] = self.last_good_transcript_at.isoformat()
        return payload


class AudioQualityService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._states: dict[str, CallAudioState] = {}

    def get_state(self, call_sid: str) -> CallAudioState:
        if call_sid not in self._states:
            self._states[call_sid] = CallAudioState(call_sid=call_sid)
        return self._states[call_sid]

    def assess_turn(
        self,
        *,
        call_sid: str,
        transcript: str,
        confidence: float | None,
        confidence_source: str,
        speech_detected: bool,
    ) -> tuple[CallAudioState, AudioQualityAssessment]:
        state = self.get_state(call_sid)
        cleaned = transcript.strip()
        short_valid_intent = is_short_valid_intent(cleaned)
        effective_confidence = confidence if confidence is not None else 0.0
        low_confidence = effective_confidence < self.settings.stt_confidence_threshold and not short_valid_intent
        no_meaningful_input = (not cleaned or not speech_detected) and not short_valid_intent
        likely_noisy = no_meaningful_input or low_confidence

        if short_valid_intent:
            state.consecutive_unclear_count = 0
            state.retry_count = 0
            state.noise_flag = False
            state.short_response_mode = False
            state.last_good_transcript_at = utc_now()
            state.last_reason = "short-valid-intent"
        elif no_meaningful_input:
            state.empty_input_count += 1
            state.consecutive_unclear_count += 1
            state.retry_count += 1
            state.last_reason = "empty-or-no-speech"
        elif low_confidence:
            state.low_confidence_count += 1
            state.consecutive_unclear_count += 1
            state.retry_count += 1
            state.last_reason = "low-confidence"
        else:
            state.consecutive_unclear_count = 0
            state.retry_count = 0
            state.noise_flag = False
            state.short_response_mode = False
            state.last_good_transcript_at = utc_now()
            state.last_reason = "clear-turn"

        if state.consecutive_unclear_count >= self.settings.noisy_call_retry_prompt_trigger:
            state.noise_flag = True
            state.short_response_mode = True

        if state.consecutive_unclear_count >= self.settings.noisy_call_fallback_trigger:
            state.fallback_mode = True
            state.noise_flag = True
            state.short_response_mode = True

        state.last_confidence = effective_confidence
        state.last_confidence_source = confidence_source
        state.last_quality_label = self._quality_label(state)

        assessment = AudioQualityAssessment(
            transcript_reliable=(bool(cleaned) and not low_confidence and speech_detected) or short_valid_intent,
            likely_noisy=likely_noisy or state.noise_flag,
            retry_recommended=state.consecutive_unclear_count < self.settings.noisy_call_fallback_trigger,
            fallback_recommended=state.fallback_mode,
            speech_detected=speech_detected,
            confidence=effective_confidence,
            confidence_source=confidence_source,
            reason=state.last_reason,
            quality_label=state.last_quality_label,
        )
        return state, assessment

    def register_success(self, call_sid: str, transcript: str) -> CallAudioState:
        state = self.get_state(call_sid)
        if transcript.strip():
            state.consecutive_unclear_count = 0
            state.retry_count = 0
            state.last_good_transcript_at = utc_now()
            state.last_reason = "clear-turn"
            state.last_quality_label = self._quality_label(state)
        return state

    def normalize_noisy_intent(self, text: str) -> str | None:
        normalized = text.strip().lower()
        if not normalized:
            return None

        intent_map = {
            "yes": ["yes", "haan", "ha", "ji", "okay", "ok"],
            "no": ["no", "nahin", "nahi", "nope"],
            "busy": ["busy", "later", "call later", "abhi busy"],
            "callback": ["callback", "call back", "call me later", "phone later"],
            "send_link": ["send link", "sms", "message", "link", "send me link"],
            "repeat": ["repeat", "again", "say again", "dobara", "phir se"],
            "not_interested": ["not interested", "stop", "unsubscribe", "mat call karo"],
        }
        for intent, phrases in intent_map.items():
            if normalized == intent.replace("_", " ") or any(phrase in normalized for phrase in phrases):
                return intent
        return None

    @staticmethod
    def should_use_short_responses(state: CallAudioState) -> bool:
        return state.short_response_mode or state.fallback_mode or state.noise_flag

    @staticmethod
    def _quality_label(state: CallAudioState) -> str:
        if state.fallback_mode:
            return "fallback"
        if state.noise_flag:
            return "noisy"
        if state.consecutive_unclear_count:
            return "caution"
        return "clear"


_audio_quality_service: AudioQualityService | None = None


def get_audio_quality_service(settings: Settings) -> AudioQualityService:
    global _audio_quality_service
    if _audio_quality_service is None:
        _audio_quality_service = AudioQualityService(settings)
    return _audio_quality_service
