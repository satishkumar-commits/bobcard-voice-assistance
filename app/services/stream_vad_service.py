import audioop
import logging
import math

from app.core.config import Settings

try:
    import webrtcvad
except ImportError:  # pragma: no cover - fallback if optional dependency is missing
    webrtcvad = None  # type: ignore[assignment]


logger = logging.getLogger(__name__)


class StreamVADService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.requested_backend = (settings.stream_vad_backend or "rms").strip().lower()
        self.backend = "rms"
        self._webrtc_vad: object | None = None

        if self.requested_backend == "webrtc":
            if webrtcvad is None:
                logger.warning("WebRTC VAD requested but dependency is unavailable. Falling back to RMS VAD.")
            else:
                aggressiveness = min(3, max(0, int(settings.stream_webrtc_vad_aggressiveness)))
                self._webrtc_vad = webrtcvad.Vad(aggressiveness)
                self.backend = "webrtc"
        elif self.requested_backend != "rms":
            logger.warning("Unknown stream VAD backend '%s'. Falling back to RMS VAD.", self.requested_backend)

        logger.info("Stream VAD initialized with backend=%s requested_backend=%s", self.backend, self.requested_backend)

    def is_speech_frame(self, mulaw_audio: bytes, *, during_playback: bool = False) -> bool:
        if self.backend == "webrtc" and self._webrtc_vad is not None:
            try:
                return self._is_speech_webrtc(mulaw_audio, during_playback=during_playback)
            except Exception as exc:  # pragma: no cover - provider fallback path
                logger.warning("WebRTC VAD frame check failed, falling back to RMS for this frame: %s", exc)
        return self._is_speech_rms(mulaw_audio, during_playback=during_playback)

    def _is_speech_rms(self, mulaw_audio: bytes, *, during_playback: bool) -> bool:
        linear_pcm = audioop.ulaw2lin(mulaw_audio, 2)
        rms = audioop.rms(linear_pcm, 2)
        threshold = self.settings.stream_vad_rms_threshold
        if during_playback:
            # During assistant playback, be stricter to reduce echo-triggered false barge-ins.
            threshold = max(420, int(threshold * 1.35))
        return rms >= threshold

    def _is_speech_webrtc(self, mulaw_audio: bytes, *, during_playback: bool) -> bool:
        assert self._webrtc_vad is not None
        linear_pcm = audioop.ulaw2lin(mulaw_audio, 2)
        if not linear_pcm:
            return False

        frame_ms = self._normalized_frame_ms(self.settings.stream_webrtc_vad_frame_ms)
        bytes_per_frame = int((8000 * frame_ms / 1000) * 2)
        if bytes_per_frame <= 0:
            return False

        total_frames = max(1, math.ceil(len(linear_pcm) / bytes_per_frame))
        speech_frames = 0
        for frame_index in range(total_frames):
            start = frame_index * bytes_per_frame
            end = start + bytes_per_frame
            frame = linear_pcm[start:end]
            if len(frame) < bytes_per_frame:
                frame += b"\x00" * (bytes_per_frame - len(frame))
            if self._webrtc_vad.is_speech(frame, 8000):
                speech_frames += 1

        if during_playback:
            # During playback, require a stronger speech ratio to avoid assistant echo being treated as customer speech.
            required_frames = max(2, math.ceil(total_frames * 0.65))
            return speech_frames >= required_frames

        ratio = self.settings.stream_webrtc_vad_min_speech_ratio
        required_frames = max(1, math.ceil(total_frames * max(0.1, min(1.0, ratio))))
        return speech_frames >= required_frames

    @staticmethod
    def _normalized_frame_ms(frame_ms: int) -> int:
        if frame_ms in {10, 20, 30}:
            return frame_ms
        return 20


_stream_vad_service: StreamVADService | None = None


def get_stream_vad_service(settings: Settings) -> StreamVADService:
    global _stream_vad_service
    if _stream_vad_service is None:
        _stream_vad_service = StreamVADService(settings)
    return _stream_vad_service
