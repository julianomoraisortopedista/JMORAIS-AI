from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from .domain import (
    Tenant, TenantAuthorizationRejected, TenantContext, TenantResolutionRejected,
    TenantSecurityEvent, TenantSecurityEventType, TenantStatus,
)


class TrustedTenantResolutionService:
    def __init__(self, repository, audit, *, clock=None):
        self._repository, self._audit = repository, audit
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def resolve(self, organization_id: str, *, principal_id: str | None,
                correlation_id: str, policy_version: str) -> Tenant:
        tenant = self._repository.resolve_organization(organization_id)
        if tenant is None or tenant.status is not TenantStatus.ACTIVE:
            self._event(TenantSecurityEventType.RESOLUTION_FAILURE, tenant, organization_id,
                        principal_id, correlation_id, "TENANT_NOT_ACTIVE", policy_version)
            raise TenantResolutionRejected("active tenant cannot be resolved")
        return tenant

    def _event(self, kind, tenant, organization_id, principal_id, correlation_id, reason, policy):
        self._audit.append(TenantSecurityEvent("tenant_" + uuid4().hex, kind,
            tenant.tenant_id if tenant else None, organization_id or None, principal_id,
            correlation_id, reason, policy, self._clock()))


class CanonicalTenantAuthorizationService:
    def __init__(self, audit, *, clock=None):
        self._audit = audit
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def authorize(self, *, tenant: Tenant, principal_id: str, organization_id: str,
                  role: str, purpose: str, policy_version: str,
                  correlation_id: str) -> TenantContext:
        if tenant.status is not TenantStatus.ACTIVE or tenant.organization_id != organization_id:
            self._deny(TenantSecurityEventType.CROSS_TENANT_DENIAL, tenant,
                       organization_id, principal_id, correlation_id,
                       "ORGANIZATION_TENANT_MISMATCH", policy_version)
        if tenant.policy_version != policy_version:
            self._deny(TenantSecurityEventType.UNAUTHORIZED_ASSOCIATION, tenant,
                       organization_id, principal_id, correlation_id,
                       "TENANT_POLICY_MISMATCH", policy_version)
        return TenantContext(tenant.tenant_id, organization_id, principal_id, role, purpose,
                             policy_version, correlation_id)

    def _deny(self, kind, tenant, organization, principal, correlation, reason, policy):
        self._audit.append(TenantSecurityEvent("tenant_" + uuid4().hex,
            kind, tenant.tenant_id,
            organization, principal, correlation, reason, policy, self._clock()))
        raise TenantAuthorizationRejected("tenant association is not authorized")
