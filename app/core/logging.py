import logging
import re
from typing import Any


_SENSITIVE_FIELD_NAMES = {
    "api_key",
    "apikey",
    "auth",
    "auth_token",
    "authorization",
    "from_number",
    "mobile_number",
    "phone",
    "phone_number",
    "recording_url",
    "secret",
    "token",
    "to_number",
    "twilio_auth_token",
}

_TWILIO_SID_PATTERN = re.compile(r"\b(?:CA|RE|AC|PN|SM|MM)[0-9a-fA-F]{32}\b")
_PHONE_PATTERN = re.compile(r"(?<!\w)(\+?\d[\d\s\-()]{6,}\d)(?!\w)")
_RECORDING_URL_PATTERN = re.compile(r"https?://[^\s]+(?:recording|recordings)[^\s]*", re.IGNORECASE)
_BEARER_TOKEN_PATTERN = re.compile(r"(?i)(bearer\s+)([a-z0-9._\-]+)")


class SensitiveDataFilter(logging.Filter):
    """Redacts common secrets/PII before log records are emitted."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_text(record.msg)
        if record.args:
            record.args = redact_value(record.args)
        return True


def mask_sid(value: str) -> str:
    normalized = value.strip()
    if len(normalized) < 10:
        return "[REDACTED_SID]"
    return f"{normalized[:4]}...{normalized[-4:]}"


def mask_phone(value: str) -> str:
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) < 4:
        return "[REDACTED_PHONE]"
    return f"***{digits[-4:]}"


def redact_text(value: str) -> str:
    redacted = _TWILIO_SID_PATTERN.sub(lambda m: mask_sid(m.group(0)), value)
    redacted = _RECORDING_URL_PATTERN.sub("[REDACTED_RECORDING_URL]", redacted)
    redacted = _BEARER_TOKEN_PATTERN.sub(r"\1[REDACTED_TOKEN]", redacted)

    def _replace_phone(match: re.Match[str]) -> str:
        candidate = match.group(1)
        if sum(ch.isdigit() for ch in candidate) < 8:
            return candidate
        return mask_phone(candidate)

    return _PHONE_PATTERN.sub(_replace_phone, redacted)


def redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, dict):
        return sanitize_log_payload(value)
    return value


def sanitize_log_payload(payload: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, value in payload.items():
        key_name = str(key).lower()
        if key_name in _SENSITIVE_FIELD_NAMES:
            if "sid" in key_name:
                sanitized[key] = mask_sid(str(value)) if value else "[REDACTED]"
            elif "phone" in key_name or "number" in key_name:
                sanitized[key] = mask_phone(str(value)) if value else "[REDACTED]"
            elif "url" in key_name:
                sanitized[key] = "[REDACTED_URL]"
            else:
                sanitized[key] = "[REDACTED]"
            continue

        if key_name == "call_sid":
            sanitized[key] = mask_sid(str(value)) if value else ""
            continue

        sanitized[key] = redact_value(value)
    return sanitized


def _suppress_noisy_third_party_loggers(app_env: str) -> None:
    # Twilio HTTP client logs request/response details that are too verbose for normal operation.
    # Keep this suppressed across all environments unless explicitly overridden by logger config.
    always_suppressed = {
        "twilio.http_client": logging.WARNING,
    }
    for logger_name, level in always_suppressed.items():
        logging.getLogger(logger_name).setLevel(level)

    if app_env.lower() not in {"prod", "production"}:
        return

    for logger_name, level in {
        "httpx": logging.WARNING,
        "httpcore": logging.WARNING,
        "websockets": logging.WARNING,
        "uvicorn.access": logging.WARNING,
        "urllib3": logging.WARNING,
        "sqlalchemy.engine": logging.WARNING,
    }.items():
        logging.getLogger(logger_name).setLevel(level)


def configure_logging(level: str = "INFO", app_env: str = "development") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        force=True,
    )

    root_logger = logging.getLogger()
    has_filter = any(isinstance(log_filter, SensitiveDataFilter) for log_filter in root_logger.filters)
    if not has_filter:
        root_logger.addFilter(SensitiveDataFilter())

    for handler in root_logger.handlers:
        if not any(isinstance(log_filter, SensitiveDataFilter) for log_filter in handler.filters):
            handler.addFilter(SensitiveDataFilter())

    _suppress_noisy_third_party_loggers(app_env)
