from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class TenantError(RuntimeError): pass
class TenantResolutionRejected(TenantError): pass
class TenantAuthorizationRejected(TenantError): pass
class MissingTenantContext(TenantError): pass


class TenantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DISABLED = "DISABLED"


class TenantSecurityEventType(str, Enum):
    RESOLUTION_FAILURE = "TENANT_RESOLUTION_FAILURE"
    CROSS_TENANT_DENIAL = "CROSS_TENANT_ACCESS_DENIAL"
    MISSING_CONTEXT = "MISSING_TENANT_CONTEXT"
    UNAUTHORIZED_ASSOCIATION = "UNAUTHORIZED_TENANT_ASSOCIATION"


def _required(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise TenantError(f"{name} is required")


@dataclass(frozen=True)
class Tenant:
    tenant_id: str
    organization_id: str
    display_name: str
    status: TenantStatus
    policy_version: str
    created_at: datetime

    def __post_init__(self) -> None:
        for value, name in ((self.tenant_id, "tenant_id"), (self.organization_id, "organization_id"),
                            (self.display_name, "display_name"), (self.policy_version, "policy_version")):
            _required(value, name)
        if self.created_at.tzinfo is None:
            raise TenantError("tenant timestamp must be timezone-aware")


@dataclass(frozen=True)
class TenantContext:
    tenant_id: str
    organization_id: str
    principal_id: str
    role: str
    purpose: str
    policy_version: str
    correlation_id: str

    def __post_init__(self) -> None:
        for name, value in self.__dict__.items():
            _required(value, name)


@dataclass(frozen=True)
class TenantSecurityEvent:
    event_id: str
    event_type: TenantSecurityEventType
    tenant_id: str | None
    organization_id: str | None
    principal_id: str | None
    correlation_id: str
    reason_code: str
    policy_version: str
    occurred_at: datetime
