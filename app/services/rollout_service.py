import hashlib
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.core.config import Settings, get_settings


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class RolloutDecision:
    call_sid: str
    bucket: int
    llm_streaming: bool
    tts_persistent_ws: bool
    tts_native_mulaw: bool
    rollback_active: bool
    rollback_until: str | None

    def as_payload(self) -> dict[str, str | int | bool | None]:
        return {
            "call_sid": self.call_sid,
            "bucket": self.bucket,
            "llm_streaming": self.llm_streaming,
            "tts_persistent_ws": self.tts_persistent_ws,
            "tts_native_mulaw": self.tts_native_mulaw,
            "rollback_active": self.rollback_active,
            "rollback_until": self.rollback_until,
        }


class RolloutService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._critical_alerts: deque[datetime] = deque()
        self._rollback_until: datetime | None = None

    def get_decision(self, call_sid: str) -> RolloutDecision:
        normalized_call_sid = (call_sid or "").strip() or "global"
        bucket = self._bucket_for_call(normalized_call_sid)
        rollback_active = self.is_rollback_active()
        rollback_until_iso = self._rollback_until.isoformat() if self._rollback_until else None

        if not self.settings.rollout_enabled:
            return RolloutDecision(
                call_sid=normalized_call_sid,
                bucket=bucket,
                llm_streaming=self.settings.llm_streaming and not rollback_active,
                tts_persistent_ws=self.settings.tts_persistent_ws and not rollback_active,
                tts_native_mulaw=self.settings.tts_native_mulaw and not rollback_active,
                rollback_active=rollback_active,
                rollback_until=rollback_until_iso,
            )

        return RolloutDecision(
            call_sid=normalized_call_sid,
            bucket=bucket,
            llm_streaming=self._feature_enabled_for_bucket(
                base_enabled=self.settings.llm_streaming,
                bucket=bucket,
                percent=self.settings.rollout_llm_streaming_percent,
                rollback_active=rollback_active,
            ),
            tts_persistent_ws=self._feature_enabled_for_bucket(
                base_enabled=self.settings.tts_persistent_ws,
                bucket=bucket,
                percent=self.settings.rollout_tts_persistent_ws_percent,
                rollback_active=rollback_active,
            ),
            tts_native_mulaw=self._feature_enabled_for_bucket(
                base_enabled=self.settings.tts_native_mulaw,
                bucket=bucket,
                percent=self.settings.rollout_tts_native_mulaw_percent,
                rollback_active=rollback_active,
            ),
            rollback_active=rollback_active,
            rollback_until=rollback_until_iso,
        )

    def record_slo_alert(self, alert_event: dict[str, object]) -> bool:
        if not self.settings.rollout_auto_rollback_enabled:
            return False
        if str(alert_event.get("severity") or "").lower() != "critical":
            return False

        now = utc_now()
        window_seconds = max(30, int(self.settings.rollout_rollback_alert_window_seconds))
        self._critical_alerts.append(now)
        self._trim_critical_alerts(now=now, window_seconds=window_seconds)
        threshold = max(1, int(self.settings.rollout_rollback_critical_alerts_threshold))
        if len(self._critical_alerts) < threshold:
            return False

        duration_seconds = max(60, int(self.settings.rollout_rollback_duration_seconds))
        next_rollback_until = now + timedelta(seconds=duration_seconds)
        if self._rollback_until and self._rollback_until > next_rollback_until:
            return False
        self._rollback_until = next_rollback_until
        return True

    def is_rollback_active(self) -> bool:
        if self._rollback_until is None:
            return False
        if utc_now() >= self._rollback_until:
            self._rollback_until = None
            return False
        return True

    def rollback_until_iso(self) -> str | None:
        if not self.is_rollback_active():
            return None
        return self._rollback_until.isoformat() if self._rollback_until else None

    def _trim_critical_alerts(self, *, now: datetime, window_seconds: int) -> None:
        cutoff = now - timedelta(seconds=window_seconds)
        while self._critical_alerts and self._critical_alerts[0] < cutoff:
            self._critical_alerts.popleft()

    @staticmethod
    def _bucket_for_call(call_sid: str) -> int:
        digest = hashlib.sha256(call_sid.encode("utf-8")).hexdigest()
        return int(digest[:8], 16) % 100

    @staticmethod
    def _feature_enabled_for_bucket(
        *,
        base_enabled: bool,
        bucket: int,
        percent: int,
        rollback_active: bool,
    ) -> bool:
        if rollback_active:
            return False
        if not base_enabled:
            return False
        bounded_percent = min(100, max(0, int(percent)))
        return bucket < bounded_percent


_rollout_service: RolloutService | None = None


def get_rollout_service() -> RolloutService:
    global _rollout_service
    if _rollout_service is None:
        _rollout_service = RolloutService(get_settings())
    return _rollout_service
