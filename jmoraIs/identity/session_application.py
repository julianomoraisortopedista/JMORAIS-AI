from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from time import monotonic
from uuid import uuid4

from jmoraIs.api.security import ApiMetric, ReadinessCheck
from .domain import PrincipalType
from .session_domain import (
    SessionRevocationEvent, SessionSecurityEventType, SessionSecurityPolicy, SessionStatus,
    SessionValidationRejected, SessionValidationRequest,
)


class CanonicalSessionSecurityService:
    def __init__(self, sessions, replay, audit, policy: SessionSecurityPolicy, *, clock=None, metrics=None):
        self._sessions, self._replay, self._audit, self._policy, self._metrics = sessions, replay, audit, policy, metrics
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def validate(self, request: SessionValidationRequest) -> None:
        started = monotonic(); now = self._clock(); reason = "VALID"
        try:
            if not self._policy.validation_enabled: raise SessionValidationRejected("session validation is disabled")
            candidate = request.session
            previously_known = self._sessions.get(candidate.session_id.value)
            existing = self._sessions.recognize(candidate)
            if previously_known is None:
                self._event(SessionSecurityEventType.SESSION_RECOGNIZED, request, "RECOGNIZED")
            if (existing.principal_id != candidate.principal_id or existing.tenant_id != candidate.tenant_id
                    or existing.organization_id != candidate.organization_id or existing.issuer != candidate.issuer
                    or existing.principal_type is not candidate.principal_type):
                reason = "INVALID_ASSOCIATION"; self._event(SessionSecurityEventType.ASSOCIATION_REJECTED, request, reason)
                raise SessionValidationRejected("session association is invalid")
            status = self._sessions.status(candidate.session_id.value, candidate.principal_id)
            if status is SessionStatus.REVOKED:
                reason = "REVOKED"; raise SessionValidationRejected("session is revoked")
            if status is SessionStatus.SUSPENDED:
                reason = "SUSPENDED"; raise SessionValidationRejected("session is suspended")
            if now > candidate.expires_at + timedelta(seconds=self._policy.clock_skew_seconds):
                reason = "EXPIRED"; self._event(SessionSecurityEventType.SESSION_EXPIRED, request, reason)
                raise SessionValidationRejected("session is expired")
            if candidate.principal_type is PrincipalType.HUMAN and self._policy.require_human_jti and not request.jti:
                reason = "JTI_REQUIRED"; raise SessionValidationRejected("human session JTI is required")
            if request.jti and self._policy.replay_protection_enabled:
                digest = sha256(f"{candidate.issuer}|{request.jti}".encode()).hexdigest()
                single_use = request.token_class in self._policy.single_use_token_classes
                if not self._replay.consume(jti_hash=digest, session=candidate, consumed_at=now, single_use=single_use):
                    reason = "REPLAY"; self._event(SessionSecurityEventType.REPLAY_DETECTED, request, reason)
                    raise SessionValidationRejected("token replay detected")
        finally:
            if self._metrics is not None:
                self._metrics.observe(ApiMetric("/identity/session-validation", "IDENTITY", 200 if reason == "VALID" else 401,
                    round((monotonic() - started) * 1000, 3), now, "SESSION_" + reason))

    def revoke_session(self, session_id, principal_id, tenant_id, *, reason, correlation_id):
        return self._append(SessionSecurityEventType.SESSION_REVOKED, session_id, principal_id, tenant_id, reason, correlation_id)
    def suspend_session(self, session_id, principal_id, tenant_id, *, reason, correlation_id):
        return self._append(SessionSecurityEventType.SESSION_SUSPENDED, session_id, principal_id, tenant_id, reason, correlation_id)
    def revoke_principal(self, principal_id, tenant_id, *, reason, correlation_id):
        return self._append(SessionSecurityEventType.PRINCIPAL_SESSIONS_REVOKED, None, principal_id, tenant_id, reason, correlation_id)
    def readiness(self):
        checks = (self._sessions.readiness(), self._replay.readiness())
        return ReadinessCheck("session_security", all(x.ready for x in checks), "AVAILABLE" if all(x.ready for x in checks) else "UNAVAILABLE")
    def _append(self, kind, session_id, principal_id, tenant_id, reason, correlation_id):
        event = SessionRevocationEvent("ses_" + uuid4().hex, kind, session_id, principal_id, tenant_id,
            reason, correlation_id, self._policy.policy_version, self._clock())
        self._sessions.append_event(event); self._audit.append(event); return event
    def _event(self, kind, request, reason):
        event = SessionRevocationEvent("ses_" + uuid4().hex, kind, request.session.session_id.value,
            request.session.principal_id, request.session.tenant_id, reason, request.correlation_id,
            self._policy.policy_version, self._clock())
        self._audit.append(event)
