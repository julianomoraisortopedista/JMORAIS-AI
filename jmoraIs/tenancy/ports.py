from __future__ import annotations

from typing import Protocol

from .domain import Tenant, TenantContext, TenantSecurityEvent


class TenantRepository(Protocol):
    def get(self, tenant_id: str) -> Tenant | None: ...
    def resolve_organization(self, organization_id: str) -> Tenant | None: ...
    def readiness(self): ...


class TenantResolutionPort(Protocol):
    def resolve(self, organization_id: str, *, principal_id: str | None,
                correlation_id: str, policy_version: str) -> Tenant: ...


class TenantAuthorizationPort(Protocol):
    def authorize(self, *, tenant: Tenant, principal_id: str, organization_id: str,
                  role: str, purpose: str, policy_version: str,
                  correlation_id: str) -> TenantContext: ...


class TenantContextBindingPort(Protocol):
    def bind(self, caller): ...
    def bind_tenant(self, context: TenantContext): ...


class TenantSecurityAuditPort(Protocol):
    def append(self, event: TenantSecurityEvent) -> None: ...
    def history(self, correlation_id: str) -> tuple[TenantSecurityEvent, ...]: ...
