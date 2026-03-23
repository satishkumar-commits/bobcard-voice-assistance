from functools import lru_cache
from pathlib import Path

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

    # Sarvam speech-to-text and text-to-speech provider settings.
    sarvam_api_key: str = ""
    sarvam_base_url: str = "https://api.sarvam.ai"
    sarvam_stt_model: str = "saaras:v3"
    sarvam_stt_use_streaming: bool = True
    sarvam_stt_streaming_mode: str = "transcribe"
    sarvam_stt_streaming_high_vad_sensitivity: bool = True
    sarvam_tts_model: str = "bulbul:v3"
    sarvam_tts_voice: str = "simran"
    sarvam_tts_pace: float = 1.0
    sarvam_tts_sample_rate: int = 22050
    sarvam_tts_enable_preprocessing: bool = True
    sarvam_tts_use_streaming: bool = True
    sarvam_tts_output_audio_codec: str = "linear16"
    sarvam_tts_output_audio_bitrate: str = "128k"
    sarvam_tts_streaming_min_buffer_size: int = 40
    sarvam_tts_streaming_max_chunk_length: int = 120

    # Gemini response generation settings.
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash-lite"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"

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
    webrtc_ice_servers: str = "stun:stun.l.google.com:19302"
    stt_confidence_threshold: float = 0.55
    vad_min_audio_bytes: int = 12000
    noisy_call_retry_prompt_trigger: int = 2
    noisy_call_fallback_trigger: int = 3
    stream_vad_rms_threshold: int = 450
    stream_vad_silence_ms: int = 420
    stream_vad_min_speech_ms: int = 280
    stream_vad_max_speech_ms: int = 9000
    stream_barge_in_grace_ms: int = 350
    stream_barge_in_min_playback_ms: int = 650
    stream_barge_in_min_speech_ms: int = 240
    stream_utterance_queue_maxsize: int = 2
    tts_cache_max_entries: int = 96

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
    def webrtc_ice_server_list(self) -> list[str]:
        # Allow multiple ICE servers through a single comma-separated env var.
        return [item.strip() for item in self.webrtc_ice_servers.split(",") if item.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    # Reuse one parsed settings instance across the app lifetime.
    return Settings()
