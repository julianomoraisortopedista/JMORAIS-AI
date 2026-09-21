from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from jmoraIs.clinical.governance_persistence import PostgreSQLReviewerIdentityRepository
from jmoraIs.clinical.review_governance import ReviewerIdentity, ReviewerRole
from jmoraIs.infrastructure.tenant_database import create_tenant_runtime_engine
from jmoraIs.infrastructure.tenant_persistence import (
    CANONICAL_TENANT_TABLES, PostgreSQLRLSReadiness, PostgreSQLTenantRepository,
    PostgreSQLTenantSecurityAudit,
)
from jmoraIs.tenancy.context import TenantContextBinder
from jmoraIs.tenancy.domain import TenantContext, TenantSecurityEvent, TenantSecurityEventType


NOW = datetime(2026, 8, 10, tzinfo=timezone.utc)
RUNTIME_ROLE = "jmorais_application_writer"
REQUIRED_RLS = CANONICAL_TENANT_TABLES


def migrated():
    url = os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url: pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    config = Config("alembic.ini"); config.set_main_option("sqlalchemy.url", url); command.upgrade(config, "head")
    return url, create_engine(url, future=True)


def seed_tenants(owner):
    suffix = uuid4().hex[:12]; tenant_a, tenant_b = "tenant-a-" + suffix, "tenant-b-" + suffix
    org_a, org_b = "org-a-" + suffix, "org-b-" + suffix
    with owner.begin() as connection:
        for tenant_id, organization_id in ((tenant_a, org_a), (tenant_b, org_b)):
            connection.execute(text("INSERT INTO tenants (tenant_id,organization_id,display_name,status,policy_version,created_at) "
                "VALUES (:tenant,:organization,:name,'ACTIVE','iam-policy-v1',:created)"),
                {"tenant": tenant_id, "organization": organization_id, "name": organization_id, "created": NOW})
    return tenant_a, org_a, tenant_b, org_b


def context(tenant_id, organization_id, principal="service-principal"):
    return TenantContext(tenant_id, organization_id, principal, "INTERNAL_SERVICE",
                         "INTERNAL_OPERATIONS", "iam-policy-v1", "corr-" + uuid4().hex)


def insert_access_event(connection, event_id, tenant_id):
    connection.execute(text("""INSERT INTO api_access_audit_events
        (event_id,caller_id,role,purpose,correlation_id,policy_version,route_template,
         method,outcome,status_code,duration_ms,occurred_at,tenant_id)
        VALUES(:event,'caller','INTERNAL_SERVICE','INTERNAL_OPERATIONS',:correlation,
         'iam-policy-v1','/internal/api/v1/version','GET','ALLOWED',200,1.0,:occurred,:tenant)"""),
        {"event": event_id, "correlation": "corr-" + event_id, "occurred": NOW, "tenant": tenant_id})


@pytest.mark.integration
def test_real_runtime_role_rls_blocks_cross_tenant_read_write_and_missing_context():
    url, owner = migrated(); tenant_a, org_a, tenant_b, org_b = seed_tenants(owner)
    event_a, event_b = "api_" + uuid4().hex, "api_" + uuid4().hex
    with owner.begin() as connection:
        insert_access_event(connection, event_a, tenant_a); insert_access_event(connection, event_b, tenant_b)
    runtime = create_tenant_runtime_engine(url, runtime_role=RUNTIME_ROLE); binder = TenantContextBinder()
    with binder.bind_tenant(context(tenant_a, org_a)), runtime.connect() as connection:
        visible = connection.execute(text("SELECT event_id FROM api_access_audit_events ORDER BY event_id")).scalars().all()
        assert event_a in visible and event_b not in visible
        assert connection.execute(text("SELECT event_id FROM api_access_audit_events WHERE event_id=:id"),
                                  {"id": event_b}).first() is None
        with pytest.raises(DBAPIError): insert_access_event(connection, "api_" + uuid4().hex, tenant_b)
        connection.rollback()
    with runtime.connect() as connection:
        assert connection.execute(text("SELECT event_id FROM api_access_audit_events WHERE event_id=:id"),
                                  {"id": event_a}).first() is None
        with pytest.raises(DBAPIError): insert_access_event(connection, "api_" + uuid4().hex, tenant_a)


@pytest.mark.integration
def test_repository_without_tenant_filter_is_still_isolated_and_owner_is_not_runtime_evidence():
    url, owner = migrated(); tenant_a, org_a, tenant_b, _ = seed_tenants(owner)
    event_a, event_b = "api_" + uuid4().hex, "api_" + uuid4().hex
    with owner.begin() as connection:
        insert_access_event(connection, event_a, tenant_a); insert_access_event(connection, event_b, tenant_b)
    with owner.connect() as connection:
        assert {event_a, event_b}.issubset(set(connection.execute(text(
            "SELECT event_id FROM api_access_audit_events WHERE event_id IN (:a,:b)"), {"a": event_a, "b": event_b}).scalars()))
    runtime = create_tenant_runtime_engine(url, runtime_role=RUNTIME_ROLE)
    with TenantContextBinder().bind_tenant(context(tenant_a, org_a)), runtime.connect() as connection:
        statement = text("SELECT event_id FROM api_access_audit_events")  # intentionally no tenant predicate
        visible = set(connection.execute(statement).scalars())
        assert event_a in visible and event_b not in visible


@pytest.mark.integration
def test_runtime_role_has_no_bypass_and_cannot_disable_rls():
    url, owner = migrated(); tenant_a, org_a, _, _ = seed_tenants(owner)
    runtime = create_tenant_runtime_engine(url, runtime_role=RUNTIME_ROLE)
    with TenantContextBinder().bind_tenant(context(tenant_a, org_a)), runtime.connect() as connection:
        assert connection.execute(text("SELECT current_user")).scalar_one() == RUNTIME_ROLE
        assert connection.execute(text("SELECT rolbypassrls FROM pg_roles WHERE rolname=current_user")).scalar_one() is False
        with pytest.raises(DBAPIError): connection.execute(text("ALTER TABLE api_access_audit_events DISABLE ROW LEVEL SECURITY"))
        connection.rollback()
        connection.execute(text("SET row_security=off"))
        with pytest.raises(DBAPIError): connection.execute(text("SELECT * FROM api_access_audit_events"))


@pytest.mark.integration
def test_reviewer_and_service_repository_access_cannot_cross_tenant():
    url, owner = migrated(); tenant_a, org_a, tenant_b, org_b = seed_tenants(owner)
    reviewers = PostgreSQLReviewerIdentityRepository(owner)
    reviewer_a, reviewer_b = "reviewer-" + uuid4().hex[:20], "reviewer-" + uuid4().hex[:20]
    reviewers.save(ReviewerIdentity(reviewer_a, ReviewerRole.REVIEWER, organization_id=org_a,
        tenant_id=tenant_a, created_at=NOW, updated_at=NOW))
    reviewers.save(ReviewerIdentity(reviewer_b, ReviewerRole.REVIEWER, organization_id=org_b,
        tenant_id=tenant_b, created_at=NOW, updated_at=NOW))
    runtime_repository = PostgreSQLReviewerIdentityRepository(
        create_tenant_runtime_engine(url, runtime_role=RUNTIME_ROLE))
    with TenantContextBinder().bind_tenant(context(tenant_a, org_a, "reviewer-principal")):
        assert runtime_repository.resolve(reviewer_a).reviewer_id == reviewer_a
        assert runtime_repository.resolve(reviewer_b) is None
        with pytest.raises(DBAPIError):
            runtime_repository.save(ReviewerIdentity("reviewer-" + uuid4().hex[:20], ReviewerRole.REVIEWER,
                organization_id=org_b, tenant_id=tenant_b, created_at=NOW, updated_at=NOW))


@pytest.mark.integration
def test_rls_readiness_policies_restart_tenant_resolution_and_append_only_audit():
    url, owner = migrated(); tenant_a, org_a, _, _ = seed_tenants(owner)
    runtime = create_tenant_runtime_engine(url, runtime_role=RUNTIME_ROLE)
    readiness = PostgreSQLRLSReadiness(runtime, REQUIRED_RLS).readiness()
    assert readiness.ready and readiness.code == "ENFORCED"
    restarted = PostgreSQLTenantRepository(create_tenant_runtime_engine(url, runtime_role=RUNTIME_ROLE))
    assert restarted.resolve_organization(org_a).tenant_id == tenant_a
    audit = PostgreSQLTenantSecurityAudit(runtime); event = TenantSecurityEvent(
        "tenant_" + uuid4().hex, TenantSecurityEventType.CROSS_TENANT_DENIAL,
        tenant_a, org_a, "principal", "corr-" + uuid4().hex, "CROSS_TENANT",
        "iam-policy-v1", NOW)
    audit.append(event); assert audit.history(event.correlation_id)[-1] == event
    with pytest.raises(DBAPIError), owner.begin() as connection:
        connection.execute(text("UPDATE tenant_security_events SET reason_code='TAMPER' WHERE event_id=:id"), {"id": event.event_id})
    with owner.connect() as connection:
        enabled = set(connection.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' "
            "AND rowsecurity=true AND tablename = ANY(:tables)"), {"tables": list(REQUIRED_RLS)}).scalars())
    assert enabled == set(REQUIRED_RLS)


@pytest.mark.integration
def test_three_tenants_remain_isolated_under_concurrency_and_single_connection_pool_reuse():
    url, owner = migrated(); suffix = uuid4().hex[:12]
    identities = tuple(
        (f"tenant-{label}-{suffix}", f"org-{label}-{suffix}", f"api_{uuid4().hex}")
        for label in ("a", "b", "c")
    )
    with owner.begin() as connection:
        for tenant_id, organization_id, event_id in identities:
            connection.execute(text("INSERT INTO tenants (tenant_id,organization_id,display_name,status,policy_version,created_at) "
                "VALUES (:tenant,:organization,:name,'ACTIVE','iam-policy-v1',:created)"),
                {"tenant": tenant_id, "organization": organization_id,
                 "name": organization_id, "created": NOW})
            insert_access_event(connection, event_id, tenant_id)

    runtime = create_tenant_runtime_engine(
        url, runtime_role=RUNTIME_ROLE, pool_size=3, max_overflow=0,
    )
    binder = TenantContextBinder()

    def read_own(identity):
        tenant_id, organization_id, event_id = identity
        with binder.bind_tenant(context(tenant_id, organization_id)), runtime.connect() as connection:
            visible = tuple(connection.execute(text(
                "SELECT event_id FROM api_access_audit_events ORDER BY event_id"
            )).scalars())
            bound = connection.execute(text(
                "SELECT current_setting('jmorais.tenant_id', true)"
            )).scalar_one()
            role = connection.execute(text(
                "SELECT current_user, rolbypassrls FROM pg_roles WHERE rolname=current_user"
            )).one()
            return visible, bound, role, event_id

    with ThreadPoolExecutor(max_workers=9) as pool:
        results = tuple(pool.map(read_own, identities * 12))
    for visible, bound, role, event_id in results:
        assert visible == (event_id,)
        assert bound in {item[0] for item in identities}
        assert role == (RUNTIME_ROLE, False)

    runtime.dispose()
    reuse = create_tenant_runtime_engine(
        url, runtime_role=RUNTIME_ROLE, pool_size=1, max_overflow=0,
    )
    for identity in identities + tuple(reversed(identities)):
        tenant_id, organization_id, event_id = identity
        with binder.bind_tenant(context(tenant_id, organization_id)), reuse.connect() as connection:
            assert tuple(connection.execute(text(
                "SELECT event_id FROM api_access_audit_events ORDER BY event_id"
            )).scalars()) == (event_id,)
    with reuse.connect() as connection:
        assert tuple(connection.execute(text(
            "SELECT event_id FROM api_access_audit_events"
        )).scalars()) == ()
        assert connection.execute(text(
            "SELECT current_setting('jmorais.tenant_id', true)"
        )).scalar_one() == ""
    reuse.dispose(); owner.dispose()
