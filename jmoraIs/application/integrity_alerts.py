from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Mapping, Protocol
from uuid import uuid4


class IntegrityAlertType(str, Enum):
    TAMPERED_REPLAY = "TAMPERED_REPLAY"
    BROKEN_HASH_CHAIN = "BROKEN_HASH_CHAIN"
    APPEND_ONLY_VIOLATION = "APPEND_ONLY_VIOLATION"
    REPEATED_CONCURRENCY_FAILURE = "REPEATED_CONCURRENCY_FAILURE"
    UNAUTHORIZED_REVIEW = "UNAUTHORIZED_REVIEW"
    PACKAGE_INTEGRITY_FAILURE = "PACKAGE_INTEGRITY_FAILURE"
    MIGRATION_MISMATCH = "MIGRATION_MISMATCH"


@dataclass(frozen=True)
class IntegrityAlert:
    alert_id: str
    alert_type: IntegrityAlertType
    correlation_id: str
    occurred_at: datetime
    resource_id: str | None = None
    safe_context: Mapping[str, str] = field(default_factory=dict)


class IntegrityAlertPort(Protocol):
    def publish(self, alert: IntegrityAlert) -> None: ...


class IntegrityMonitoringService:
    """Creates deterministic, payload-free integrity alerts for external adapters."""

    def __init__(self, alerts: IntegrityAlertPort, *, clock=None) -> None:
        self._alerts = alerts
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def alert(self, alert_type: IntegrityAlertType, *, correlation_id: str,
              resource_id: str | None = None, safe_context: Mapping[str, str] | None = None) -> IntegrityAlert:
        event = IntegrityAlert(
            uuid4().hex, alert_type, correlation_id, self._clock(), resource_id,
            dict(safe_context or {}),
        )
        self._alerts.publish(event)
        return event

    def tampered_replay(self, stream: str, correlation_id: str = "replay") -> IntegrityAlert:
        return self.alert(IntegrityAlertType.TAMPERED_REPLAY, correlation_id=correlation_id,
                          resource_id=stream)

    def unauthorized_review(self, reviewer_id: str, correlation_id: str = "review") -> IntegrityAlert:
        return self.alert(IntegrityAlertType.UNAUTHORIZED_REVIEW, correlation_id=correlation_id,
                          resource_id=reviewer_id)

    def package_integrity_failure(self, package_id: str, correlation_id: str = "package") -> IntegrityAlert:
        return self.alert(IntegrityAlertType.PACKAGE_INTEGRITY_FAILURE,
                          correlation_id=correlation_id, resource_id=package_id)
