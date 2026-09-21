from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from jmoraIs.api.app import create_app
from jmoraIs.tenancy.application import CanonicalTenantAuthorizationService, TrustedTenantResolutionService
from jmoraIs.tenancy.context import TenantContextBinder, current_tenant_context
from jmoraIs.tenancy.domain import (
    MissingTenantContext, Tenant, TenantAuthorizationRejected, TenantContext,
    TenantResolutionRejected, TenantSecurityEventType, TenantStatus,
)
from tests.test_internal_api import headers, operational, services


NOW = datetime(2026, 8, 10, tzinfo=timezone.utc)


class Repository:
    def __init__(self, tenant): self.tenant = tenant
    def resolve_organization(self, organization):
        return self.tenant if self.tenant.organization_id == organization else None


class Audit:
    def __init__(self): self.events = []
    def append(self, event): self.events.append(event)


def tenant(): return Tenant("tenant-a", "organization-a", "Organization A", TenantStatus.ACTIVE, "policy-v1", NOW)


def test_immutable_tenant_and_context_models():
    value = tenant()
    context = TenantContext("tenant-a", "organization-a", "principal-a", "CLINICAL_REVIEWER",
                            "CLINICAL_REVIEW", "policy-v1", "corr-a")
    with pytest.raises(FrozenInstanceError): value.tenant_id = "tenant-b"
    with pytest.raises(FrozenInstanceError): context.tenant_id = "tenant-b"


def test_principal_resolves_trusted_tenant_and_authorization_builds_complete_context():
    audit = Audit(); resolver = TrustedTenantResolutionService(Repository(tenant()), audit, clock=lambda: NOW)
    resolved = resolver.resolve("organization-a", principal_id="principal-a",
                                correlation_id="corr-a", policy_version="policy-v1")
    context = CanonicalTenantAuthorizationService(audit, clock=lambda: NOW).authorize(
        tenant=resolved, principal_id="principal-a", organization_id="organization-a",
        role="CLINICAL_REVIEWER", purpose="CLINICAL_REVIEW", policy_version="policy-v1",
        correlation_id="corr-a")
    assert context.tenant_id == "tenant-a" and context.principal_id == "principal-a"


def test_resolution_and_cross_organization_association_fail_closed_and_are_audited():
    audit = Audit(); resolver = TrustedTenantResolutionService(Repository(tenant()), audit, clock=lambda: NOW)
    with pytest.raises(TenantResolutionRejected):
        resolver.resolve("unknown", principal_id="principal", correlation_id="corr-missing", policy_version="policy-v1")
    with pytest.raises(TenantAuthorizationRejected):
        CanonicalTenantAuthorizationService(audit, clock=lambda: NOW).authorize(
            tenant=tenant(), principal_id="principal", organization_id="organization-b",
            role="CLINICAL_REVIEWER", purpose="CLINICAL_REVIEW", policy_version="policy-v1",
            correlation_id="corr-cross")
    assert {event.reason_code for event in audit.events} == {"TENANT_NOT_ACTIVE", "ORGANIZATION_TENANT_MISMATCH"}
    assert audit.events[-1].event_type is TenantSecurityEventType.CROSS_TENANT_DENIAL
    assert "clinical" not in repr(audit.events).lower()


def test_context_binding_is_scoped_and_missing_context_fails_closed():
    binder = TenantContextBinder()
    with pytest.raises(MissingTenantContext): current_tenant_context()
    context = TenantContext("tenant-a", "organization-a", "principal-a", "ROLE", "PURPOSE", "policy-v1", "corr")
    with binder.bind_tenant(context): assert current_tenant_context() == context
    with pytest.raises(MissingTenantContext): current_tenant_context()


def test_caller_supplied_tenant_header_is_rejected():
    response = TestClient(create_app(services(), operational())).get(
        "/internal/api/v1/version", headers={**headers(), "x-tenant-id": "tenant-spoof"})
    assert response.status_code == 401 and response.json()["code"] == "TENANT_SPOOFING_REJECTED"


def test_malformed_request_tenant_context_is_audited_and_rejected():
    from types import SimpleNamespace
    audit = Audit(); binder = TenantContextBinder(audit, clock=lambda: NOW)
    caller = SimpleNamespace(tenant_id="", organization_id="organization", caller_id="principal",
        role=SimpleNamespace(value="ROLE"), purpose=SimpleNamespace(value="PURPOSE"),
        policy_version="policy-v1", correlation_id="corr-missing")
    with pytest.raises(TenantAuthorizationRejected), binder.bind(caller): pass
    assert audit.events[-1].event_type is TenantSecurityEventType.MISSING_CONTEXT


def test_api_dependency_propagates_trusted_context_into_repository_query():
    base_services = services(); base_repository = base_services.reasoning_inputs
    class ContextAssertingRepository:
        def get(self, identifier):
            assert current_tenant_context().tenant_id == "development"
            return base_repository.get(identifier)
    ops = replace(operational(), tenant_context=TenantContextBinder())
    api = TestClient(create_app(replace(base_services, reasoning_inputs=ContextAssertingRepository()), ops))
    assert api.get("/internal/api/v1/clinical-reasoning-inputs/ri-1", headers=headers()).status_code == 200
