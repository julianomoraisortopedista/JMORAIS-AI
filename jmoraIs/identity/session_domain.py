from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from .domain import PrincipalType


class SessionSecurityError(RuntimeError): pass
class SessionValidationRejected(SessionSecurityError): pass


class SessionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"
    SUSPENDED = "SUSPENDED"


class SessionSecurityEventType(str, Enum):
    SESSION_RECOGNIZED = "SESSION_RECOGNIZED"
    SESSION_REVOKED = "SESSION_REVOKED"
    PRINCIPAL_SESSIONS_REVOKED = "PRINCIPAL_SESSIONS_REVOKED"
    SESSION_SUSPENDED = "SESSION_SUSPENDED"
    REPLAY_DETECTED = "REPLAY_DETECTED"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    ASSOCIATION_REJECTED = "ASSOCIATION_REJECTED"
    SERVICE_CREDENTIAL_REVOKED = "SERVICE_CREDENTIAL_REVOKED"


@dataclass(frozen=True)
class SessionIdentifier:
    value: str
    def __post_init__(self):
        if not self.value or len(self.value) > 256: raise SessionSecurityError("valid session identifier is required")


@dataclass(frozen=True)
class AuthenticatedSession:
    session_id: SessionIdentifier
    principal_id: str
    tenant_id: str
    organization_id: str
    issuer: str
    principal_type: PrincipalType
    issued_at: datetime
    expires_at: datetime
    policy_version: str
    recognized_at: datetime
    def __post_init__(self):
        if not all((self.principal_id, self.tenant_id, self.organization_id, self.issuer, self.policy_version)):
            raise SessionSecurityError("complete session attribution is required")
        if any(value.tzinfo is None for value in (self.issued_at, self.expires_at, self.recognized_at)):
            raise SessionSecurityError("session timestamps must be timezone-aware")
        if self.expires_at <= self.issued_at: raise SessionSecurityError("session lifetime is invalid")


@dataclass(frozen=True)
class SessionValidationRequest:
    session: AuthenticatedSession
    jti: str | None
    token_class: str
    correlation_id: str


@dataclass(frozen=True)
class TokenReplayRecord:
    jti_hash: str
    session_id: str
    principal_id: str
    issuer: str
    expires_at: datetime
    consumed_at: datetime
    single_use: bool
    policy_version: str


@dataclass(frozen=True)
class SessionRevocationEvent:
    event_id: str
    event_type: SessionSecurityEventType
    session_id: str | None
    principal_id: str
    tenant_id: str
    reason_code: str
    correlation_id: str
    policy_version: str
    occurred_at: datetime


@dataclass(frozen=True)
class SessionSecurityPolicy:
    validation_enabled: bool = True
    replay_protection_enabled: bool = True
    require_human_jti: bool = True
    single_use_token_classes: tuple[str, ...] = ("SINGLE_USE",)
    clock_skew_seconds: int = 30
    replay_retention_seconds: int = 86400
    service_principal_strategy: str = "REVOCABLE_CREDENTIAL"
    policy_version: str = "session-security-v1"
    def __post_init__(self):
        if self.clock_skew_seconds < 0 or self.replay_retention_seconds < 1:
            raise SessionSecurityError("session security timing policy is invalid")
        if self.service_principal_strategy != "REVOCABLE_CREDENTIAL":
            raise SessionSecurityError("unsupported service-principal revocation strategy")
