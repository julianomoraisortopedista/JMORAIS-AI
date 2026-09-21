from __future__ import annotations

from datetime import datetime, timezone
import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from jmoraIs.clinical.governance_persistence import PostgreSQLReviewerIdentityRepository
from jmoraIs.clinical.review_governance import ReviewerIdentity, ReviewerRole
from jmoraIs.identity.application import IdentityLinkService
from jmoraIs.identity.domain import ExternalIdentityLink, IdentityLinkStatus, PrincipalType
from jmoraIs.identity.reviewer import AuthenticatedReviewerResolver
from jmoraIs.infrastructure.identity_persistence import (
    PostgreSQLExternalIdentityLinkRepository, PostgreSQLIdentitySecurityAudit,
)


NOW = datetime(2026, 8, 10, tzinfo=timezone.utc)


def migrated_engine():
    url = os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url: pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    config = Config("alembic.ini"); config.set_main_option("sqlalchemy.url", url); command.upgrade(config, "head")
    return url, create_engine(url, future=True)


def identity_link(*, reviewer_id=None, principal_type=PrincipalType.SERVICE, tenant_id="legacy-internal"):
    unique = uuid4().hex
    return ExternalIdentityLink("principal-" + unique, "oidc-test", "subject-" + unique,
        "organization-test", tenant_id, IdentityLinkStatus.ACTIVE, principal_type,
        ("INTERNAL_OPERATIONS",), ("api:read",), reviewer_id, NOW, NOW, "iam-policy-v1")


@pytest.mark.integration
def test_identity_link_restart_persistence_status_audit_and_unique_subject():
    url, engine = migrated_engine(); repository = PostgreSQLExternalIdentityLinkRepository(engine)
    audit = PostgreSQLIdentitySecurityAudit(engine); service = IdentityLinkService(repository, audit, clock=lambda: NOW)
    value = identity_link(); service.create(value, correlation_id="create-" + uuid4().hex)
    restarted = PostgreSQLExternalIdentityLinkRepository(create_engine(url, future=True))
    assert restarted.get(value.provider, value.external_subject) == value
    correlation = "suspend-" + uuid4().hex
    assert service.suspend(value.provider, value.external_subject, correlation_id=correlation).status is IdentityLinkStatus.SUSPENDED
    assert PostgreSQLIdentitySecurityAudit(create_engine(url, future=True)).history(correlation)[-1].reason_code == "LINK_SUSPENDED"
    duplicate = identity_link()
    duplicate = ExternalIdentityLink(duplicate.principal_id, value.provider, value.external_subject,
        duplicate.organization_id, duplicate.tenant_id, duplicate.status, duplicate.principal_type, duplicate.allowed_purposes,
        duplicate.scoped_permissions, None, duplicate.created_at, duplicate.last_seen_at, duplicate.policy_version)
    with pytest.raises(IntegrityError): repository.create(duplicate)


@pytest.mark.integration
def test_identity_security_history_is_append_only_and_contains_no_secret_columns():
    _, engine = migrated_engine(); repository = PostgreSQLExternalIdentityLinkRepository(engine)
    audit = PostgreSQLIdentitySecurityAudit(engine); service = IdentityLinkService(repository, audit, clock=lambda: NOW)
    value = identity_link(); correlation = "audit-" + uuid4().hex
    service.create(value, correlation_id=correlation)
    event_id = audit.history(correlation)[0].event_id
    with pytest.raises(DBAPIError), engine.begin() as connection:
        connection.execute(text("UPDATE identity_security_events SET reason_code='TAMPERED' WHERE event_id=:id"), {"id": event_id})
    with pytest.raises(DBAPIError), engine.begin() as connection:
        connection.execute(text("DELETE FROM identity_security_events WHERE event_id=:id"), {"id": event_id})
    with engine.connect() as connection:
        columns = {row[0] for row in connection.execute(text("SELECT column_name FROM information_schema.columns "
            "WHERE table_name='identity_security_events'"))}
    assert not {"token", "access_token", "password", "private_key", "clinical_payload", "patient_id"}.intersection(columns)


@pytest.mark.integration
def test_external_identity_links_reuse_existing_reviewer_directory():
    _, engine = migrated_engine(); reviewer_id = "reviewer-" + uuid4().hex[:20]
    reviewers = PostgreSQLReviewerIdentityRepository(engine)
    reviewers.save(ReviewerIdentity(reviewer_id, ReviewerRole.REVIEWER,
        organization_id="organization-test", tenant_id="tenant-test", created_at=NOW, updated_at=NOW))
    value = identity_link(reviewer_id=reviewer_id, principal_type=PrincipalType.HUMAN, tenant_id="tenant-test")
    links = PostgreSQLExternalIdentityLinkRepository(engine); links.create(value)
    from jmoraIs.identity.domain import AuthenticatedPrincipal
    principal = AuthenticatedPrincipal(value.principal_id, value.external_subject, value.provider,
        value.organization_id, value.tenant_id, ("CLINICAL_REVIEWER",), NOW, "OIDC", "session", "iam-policy-v1",
        NOW, datetime(2026, 8, 11, tzinfo=timezone.utc), PrincipalType.HUMAN,
        ("CLINICAL_REVIEW",), ("review:read",))
    assert AuthenticatedReviewerResolver(links, reviewers).resolve(principal).reviewer_id == reviewer_id
