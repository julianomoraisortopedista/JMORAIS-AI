from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Mapping


_SENSITIVE_KEYS = {
    "authorization", "password", "secret", "token", "api_key", "apikey",
    "credential", "patient_name", "patient_id", "cpf", "email", "phone",
}
_SENSITIVE_VALUE = re.compile(r"(?i)(bearer\s+[a-z0-9._-]+|password\s*[:=]\s*\S+)")


def redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]" if str(key).lower() in _SENSITIVE_KEYS else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return _SENSITIVE_VALUE.sub("[REDACTED]", value)
    return value


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
            "correlation_id": getattr(record, "correlation_id", "unknown"),
            "job_id": getattr(record, "job_id", None),
            "stream_id": getattr(record, "stream_id", None),
            "context": redact(getattr(record, "safe_context", {})),
        }
        return json.dumps(redact(payload), ensure_ascii=False, sort_keys=True)


def structured_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonLogFormatter())
        logger.addHandler(handler)
        logger.propagate = False
    return logger


def log_event(logger: logging.Logger, event: str, *, correlation_id: str,
              job_id: str | None = None, stream_id: str | None = None,
              safe_context: Mapping[str, Any] | None = None,
              level: int = logging.INFO) -> None:
    logger.log(level, event, extra={
        "correlation_id": correlation_id, "job_id": job_id,
        "stream_id": stream_id, "safe_context": redact(safe_context or {}),
    })
