from __future__ import annotations

import json
import logging
import re

from jmoraIs.api.security import ApiLogRecord

_SENSITIVE = re.compile(
    r"(?i)(bearer\s+\S+|token|password|secret|authorization|patientcontext|evidencepackage|"
    r"\bjti\b|api[_-]?key|private[_ -]?key|postgres(?:ql)?://|raw[_ -]?(?:prompt|response)|clinical[_ -]?payload)"
)


class RedactingJsonLogAdapter:
    """Structured metadata-only logger compatible with standard JSON collectors."""
    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger("jmoraIs.api.access")

    def emit(self, record: ApiLogRecord) -> None:
        payload = {
            "correlation_id": record.correlation_id, "caller_id": record.caller_id,
            "route_template": record.route_template, "purpose": record.purpose,
            "status": record.status, "duration_ms": record.duration_ms,
            "policy_version": record.policy_version, "timestamp": record.occurred_at.isoformat(),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        if _SENSITIVE.search(encoded):
            payload = {key: ("[REDACTED]" if _SENSITIVE.search(str(value)) else value)
                       for key, value in payload.items()}
            encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        self._logger.info(encoded)
