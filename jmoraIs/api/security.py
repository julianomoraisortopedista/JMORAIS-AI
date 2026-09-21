from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class CallerRole(str, Enum):
    INTERNAL_SERVICE = "INTERNAL_SERVICE"
    CLINICAL_REVIEWER = "CLINICAL_REVIEWER"
    ADMINISTRATOR = "ADMINISTRATOR"


class PurposeOfUse(str, Enum):
    INTERNAL_OPERATIONS = "INTERNAL_OPERATIONS"
    SCIENTIFIC_VALIDATION = "SCIENTIFIC_VALIDATION"
    CLINICAL_REVIEW = "CLINICAL_REVIEW"
    ADMINISTRATION = "ADMINISTRATION"


@dataclass(frozen=True)
class CallerCredentials:
    bearer_token: str
    purpose: str


@dataclass(frozen=True)
class CallerContext:
    caller_id: str
    role: CallerRole
    purpose: PurposeOfUse
    correlation_id: str
    policy_version: str
    roles: tuple[CallerRole, ...] = ()
    organization_id: str = "development"
    tenant_id: str = "development"
    principal_type: str = "SERVICE"
    scoped_permissions: tuple[str, ...] = ()


@dataclass(frozen=True)
class ApiAccessAuditEvent:
    event_id: str
    caller_id: str
    role: str
    purpose: str
    correlation_id: str
    policy_version: str
    route_template: str
    method: str
    outcome: str
    status_code: int
    duration_ms: float
    occurred_at: datetime
    tenant_id: str = "development"


@dataclass(frozen=True)
class ApiMetric:
    route_template: str
    method: str
    status_code: int
    duration_ms: float
    occurred_at: datetime
    outcome: str = "REQUEST"


@dataclass(frozen=True)
class ApiLogRecord:
    correlation_id: str
    caller_id: str
    route_template: str
    purpose: str
    status: int
    duration_ms: float
    policy_version: str
    occurred_at: datetime


@dataclass(frozen=True)
class ReadinessCheck:
    name: str
    ready: bool
    code: str


@dataclass(frozen=True)
class ReadinessReport:
    checks: tuple[ReadinessCheck, ...]

    @property
    def ready(self) -> bool:
        return bool(self.checks) and all(item.ready for item in self.checks)
