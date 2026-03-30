from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Core application settings.
    app_name: str = "BOBCards Voice Assistant"
    app_env: str = "development"
    log_level: str = "INFO"
    api_prefix: str = "/api"

    # Twilio call control and webhook integration.
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""
    twilio_validate_webhook_signature: bool = True

    # Sarvam speech-to-text and text-to-speech provider settings.
    sarvam_api_key: str = ""
    sarvam_base_url: str = "https://api.sarvam.ai"
    sarvam_stt_model: str = "saaras:v3"
    sarvam_stt_use_streaming: bool = True
    sarvam_stt_streaming_mode: str = "transcribe"
    sarvam_stt_streaming_high_vad_sensitivity: bool = False
    sarvam_stt_streaming_total_timeout_seconds: float = 8.0
    sarvam_stt_streaming_recv_timeout_seconds: float = 2.8
    sarvam_stt_streaming_cooldown_seconds: float = 20.0
    sarvam_stt_rest_timeout_seconds: float = 15.0
    sarvam_tts_model: str = "bulbul:v3"
    sarvam_tts_voice: str = "simran"
    sarvam_tts_pace: float = 1.0
    sarvam_tts_sample_rate: int = 8000
    sarvam_tts_enable_preprocessing: bool = True
    sarvam_tts_use_streaming: bool = True
    sarvam_tts_output_audio_codec: str = "mulaw"
    sarvam_tts_output_audio_bitrate: str = "128k"
    sarvam_tts_streaming_min_buffer_size: int = 40
    sarvam_tts_streaming_max_chunk_length: int = 120
    assistant_tts_max_chars: int = 220
    assistant_tts_sentence_max_chars: int = 180
    assistant_stream_flush_timeout_ms: int = 420
    assistant_stream_partial_min_chars: int = 24
    assistant_stream_force_flush_chars: int = 72
    assistant_gemini_filler_enabled: bool = True
    assistant_gemini_filler_delay_ms: int = 1500
    assistant_tts_slow_threshold_ms: int = 4500
    assistant_tts_slow_trigger_count: int = 2
    assistant_tts_slow_mode_seconds: int = 90
    assistant_tts_slow_mode_sentence_max_chars: int = 100
    tts_static_prompt_warmup: bool = False

    # Gemini response generation settings.
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash-lite"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"

    # Feature flags for phased latency refactor rollout.
    llm_streaming: bool = True
    tts_persistent_ws: bool = True
    tts_native_mulaw: bool = True

    # Storage, routing, and runtime tuning.
    database_url: str = Field(default="sqlite:///./data/voice_agent.db", alias="DATABASE_URL")
    public_url: str = ""

    cors_origins: list[str] = ["*"]
    max_conversation_turns: int = 6
    recording_max_length_seconds: int = 8
    recording_timeout_seconds: int = 2
    generated_audio_dir: str = "/tmp/bobcards_voice_generated_audio"
    generated_audio_ttl_seconds: int = 180
    dashboard_dir: str = "dashboard"
    latency_logs_dir: str = "data/latency_logs"
    webrtc_ice_servers: str = "stun:stun.l.google.com:19302"
    stt_confidence_threshold: float = 0.55
    vad_min_audio_bytes: int = 8000
    noisy_call_retry_prompt_trigger: int = 2
    noisy_call_fallback_trigger: int = 3
    stream_vad_backend: str = "webrtc"
    stream_vad_rms_threshold: int = 320
    stream_webrtc_vad_aggressiveness: int = 2
    stream_webrtc_vad_frame_ms: int = 20
    stream_webrtc_vad_min_speech_ratio: float = 0.5
    stream_vad_silence_ms: int = 620
    stream_vad_min_speech_ms: int = 260
    stream_vad_max_speech_ms: int = 7000
    stream_stt_enable_micro_chunking: bool = True
    stream_stt_chunk_ms: int = 240
    stream_stt_preroll_ms: int = 60
    stream_stt_enable_persistent_connection: bool = True
    stream_stt_persistent_finalize_timeout_seconds: float = 1.2
    stream_stt_persistent_finalize_max_messages: int = 3
    stream_stt_turn_timeout_seconds: float = 3.5
    stt_mode: Literal["auto", "rest", "streaming"] = "auto"
    stt_stream_retry_max: int = 1
    stt_stream_backoff_ms: int = 300
    stt_stream_cb_fails: int = 3
    empty_transcript_min_chars: int = 3
    barge_in_min_speech_ms: int = 520
    barge_in_cooldown_ms: int = 220
    stream_barge_in_grace_ms: int = 600
    stream_barge_in_min_playback_ms: int = 1000
    stream_barge_in_min_speech_ms: int = 760
    stream_utterance_queue_maxsize: int = 2
    tts_cache_max_entries: int = 96
    slo_alerts_enabled: bool = True
    slo_alert_cooldown_seconds: int = 30
    slo_window_size: int = 40
    slo_stt_latency_ms: int = 3500
    slo_gemini_latency_ms: int = 4500
    slo_tts_latency_ms: int = 3000
    rollout_enabled: bool = False
    rollout_llm_streaming_percent: int = 100
    rollout_tts_persistent_ws_percent: int = 100
    rollout_tts_native_mulaw_percent: int = 100
    rollout_auto_rollback_enabled: bool = True
    rollout_rollback_critical_alerts_threshold: int = 5
    rollout_rollback_alert_window_seconds: int = 300
    rollout_rollback_duration_seconds: int = 900

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def async_database_url(self) -> str:
        # SQLAlchemy async drivers need a different SQLite URL prefix.
        if self.database_url.startswith("sqlite:///"):
            return self.database_url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
        if self.database_url.startswith("sqlite://"):
            return self.database_url.replace("sqlite://", "sqlite+aiosqlite://", 1)
        return self.database_url

    @property
    def generated_audio_path(self) -> Path:
        return Path(self.generated_audio_dir)

    @property
    def dashboard_path(self) -> Path:
        return Path(self.dashboard_dir)

    @property
    def latency_logs_path(self) -> Path:
        return Path(self.latency_logs_dir)

    @property
    def webrtc_ice_server_list(self) -> list[str]:
        # Allow multiple ICE servers through a single comma-separated env var.
        return [item.strip() for item in self.webrtc_ice_servers.split(",") if item.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    # Reuse one parsed settings instance across the app lifetime.
    return Settings()
