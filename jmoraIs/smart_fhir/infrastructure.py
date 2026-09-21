from __future__ import annotations

from jmoraIs.identity.domain import IdentitySecurityEvent, IdentitySecurityEventType

from .domain import SmartAuthenticationAuditEvent


class InMemorySmartAuthenticationAudit:
    def __init__(self): self._events = []
    def append(self, event): self._events.append(event)
    def history(self, correlation_id):
        return tuple(item for item in self._events if item.correlation_id == correlation_id)


class CanonicalIdentitySecurityAuditAdapter:
    """Persists SMART metadata through the existing append-only IAM audit authority."""

    def __init__(self, audit): self._audit = audit
    def append(self, event: SmartAuthenticationAuditEvent):
        event_type = (IdentitySecurityEventType.AUTHENTICATION_SUCCESS
                      if event.outcome == "SUCCESS" else IdentitySecurityEventType.AUTHENTICATION_FAILURE)
        self._audit.append(IdentitySecurityEvent(
            event.event_id, event_type, event.subject, event.issuer,
            event.correlation_id, event.reason_code, event.policy_version, event.occurred_at,
        ))
    def history(self, correlation_id):
        return tuple(SmartAuthenticationAuditEvent(
            item.event_id,
            "SUCCESS" if item.event_type is IdentitySecurityEventType.AUTHENTICATION_SUCCESS else "FAILURE",
            item.reason_code, item.correlation_id, item.provider, item.principal_id,
            item.policy_version, item.occurred_at,
        ) for item in self._audit.history(correlation_id))
