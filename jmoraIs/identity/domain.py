from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class IdentityError(RuntimeError): pass
class IdentityAuthenticationRejected(IdentityError): pass
class IdentityAuthorizationRejected(IdentityError): pass


class PrincipalType(str, Enum):
    HUMAN = "HUMAN"
    SERVICE = "SERVICE"


class IdentityLinkStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DISABLED = "DISABLED"


class IdentitySecurityEventType(str, Enum):
    AUTHENTICATION_SUCCESS = "AUTHENTICATION_SUCCESS"
    AUTHENTICATION_FAILURE = "AUTHENTICATION_FAILURE"
    AUTHORIZATION_DENIAL = "AUTHORIZATION_DENIAL"
    IDENTITY_LINK_CREATED = "IDENTITY_LINK_CREATED"
    IDENTITY_SUSPENDED = "IDENTITY_SUSPENDED"
    UNKNOWN_ROLE = "UNKNOWN_ROLE"
    INVALID_ISSUER_AUDIENCE = "INVALID_ISSUER_AUDIENCE"
    EXPIRED_TOKEN = "EXPIRED_TOKEN"
    SIGNING_KEY_FAILURE = "SIGNING_KEY_FAILURE"
    IDENTITY_LINK_FAILURE = "IDENTITY_LINK_FAILURE"


def _required(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip(): raise IdentityError(f"{name} is required")


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    principal_id: str
    external_subject: str
    identity_provider: str
    organization_id: str
    tenant_id: str
    roles: tuple[str, ...]
    authentication_time: datetime
    authentication_method: str
    session_id: str | None
    policy_version: str
    issued_at: datetime
    expires_at: datetime
    principal_type: PrincipalType
    allowed_purposes: tuple[str, ...]
    scoped_permissions: tuple[str, ...]

    def __post_init__(self):
        for value, name in ((self.principal_id, "principal_id"), (self.external_subject, "external_subject"),
            (self.identity_provider, "identity_provider"), (self.organization_id, "organization_id"),
            (self.tenant_id, "tenant_id"),
            (self.authentication_method, "authentication_method"), (self.policy_version, "policy_version")):
            _required(value, name)
        if not self.roles or not self.allowed_purposes or self.expires_at <= self.issued_at:
            raise IdentityError("roles, purposes and valid token lifetime are required")
        if any(value.tzinfo is None for value in (self.authentication_time, self.issued_at, self.expires_at)):
            raise IdentityError("identity timestamps must be timezone-aware")


@dataclass(frozen=True)
class ExternalIdentityLink:
    principal_id: str
    provider: str
    external_subject: str
    organization_id: str
    tenant_id: str
    status: IdentityLinkStatus
    principal_type: PrincipalType
    allowed_purposes: tuple[str, ...]
    scoped_permissions: tuple[str, ...]
    reviewer_id: str | None
    created_at: datetime
    last_seen_at: datetime
    policy_version: str

    def __post_init__(self):
        for value, name in ((self.principal_id, "principal_id"), (self.provider, "provider"),
            (self.external_subject, "external_subject"), (self.organization_id, "organization_id"),
            (self.tenant_id, "tenant_id"),
            (self.policy_version, "policy_version")):
            _required(value, name)
        if self.last_seen_at < self.created_at or not self.allowed_purposes:
            raise IdentityError("identity-link timeline and purposes must be valid")


@dataclass(frozen=True)
class IdentitySecurityEvent:
    event_id: str
    event_type: IdentitySecurityEventType
    principal_id: str | None
    provider: str
    correlation_id: str
    reason_code: str
    policy_version: str
    occurred_at: datetime
