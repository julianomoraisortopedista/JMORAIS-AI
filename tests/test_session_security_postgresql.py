from datetime import datetime, timedelta, timezone
import os
from threading import Barrier, Lock, Thread
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from jmoraIs.identity.domain import PrincipalType
from jmoraIs.identity.session_application import CanonicalSessionSecurityService
from jmoraIs.identity.session_domain import (
    AuthenticatedSession, SessionIdentifier, SessionSecurityPolicy, SessionValidationRejected, SessionValidationRequest,
)
from jmoraIs.infrastructure.session_persistence import (
    PostgreSQLReplayProtectionRepository, PostgreSQLSessionRepository, PostgreSQLSessionSecurityAudit,
)
from jmoraIs.infrastructure.tenant_database import create_tenant_runtime_engine
from jmoraIs.tenancy.context import TenantContextBinder
from jmoraIs.tenancy.domain import TenantContext

NOW = datetime.now(timezone.utc).replace(microsecond=0)

def migrated():
    url = os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url: pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    config = Config("alembic.ini"); config.set_main_option("sqlalchemy.url", url); command.upgrade(config, "head")
    return url, create_engine(url, future=True)

def setup():
    url, owner = migrated(); suffix = uuid4().hex[:12]; tenant, org = "tenant-s-" + suffix, "org-s-" + suffix
    with owner.begin() as connection:
        connection.execute(text("INSERT INTO tenants (tenant_id,organization_id,display_name,status,policy_version,created_at) VALUES (:t,:o,:o,'ACTIVE','iam-policy-v1',:now)"), {"t": tenant, "o": org, "now": NOW})
    engine = create_tenant_runtime_engine(url, runtime_role="jmorais_application_writer")
    sessions, replay, audit = PostgreSQLSessionRepository(engine), PostgreSQLReplayProtectionRepository(engine), PostgreSQLSessionSecurityAudit(engine)
    service = CanonicalSessionSecurityService(sessions, replay, audit,
        SessionSecurityPolicy(single_use_token_classes=("SINGLE_USE",)), clock=lambda: NOW)
    context = TenantContext(tenant, org, "principal-1", "CLINICAL_REVIEWER", "CLINICAL_REVIEW", "session-security-v1", "corr")
    value = AuthenticatedSession(SessionIdentifier("sid-" + suffix), "principal-1", tenant, org, "https://issuer",
        PrincipalType.HUMAN, NOW - timedelta(minutes=1), NOW + timedelta(minutes=5), "session-security-v1", NOW)
    return url, owner, engine, service, context, value

@pytest.mark.integration
def test_restart_persistence_revocation_and_append_only_history():
    url, owner, engine, service, context, value = setup(); binder = TenantContextBinder()
    with binder.bind_tenant(context):
        service.validate(SessionValidationRequest(value, "jti-restart-" + uuid4().hex, "ACCESS", "corr"))
        service.revoke_session(value.session_id.value, value.principal_id, value.tenant_id, reason="ADMIN", correlation_id="corr")
    restarted = CanonicalSessionSecurityService(PostgreSQLSessionRepository(create_tenant_runtime_engine(url, runtime_role="jmorais_application_writer")),
        PostgreSQLReplayProtectionRepository(create_tenant_runtime_engine(url, runtime_role="jmorais_application_writer")),
        PostgreSQLSessionSecurityAudit(create_tenant_runtime_engine(url, runtime_role="jmorais_application_writer")), SessionSecurityPolicy(), clock=lambda: NOW)
    with binder.bind_tenant(context), pytest.raises(SessionValidationRejected, match="revoked"):
        restarted.validate(SessionValidationRequest(value, "jti-new-" + uuid4().hex, "ACCESS", "corr"))
    with pytest.raises(DBAPIError), owner.begin() as connection:
        connection.execute(text("UPDATE session_security_events SET reason_code='TAMPER' WHERE principal_id=:id"), {"id": value.principal_id})
    with owner.connect() as connection:
        columns = {x[0] for x in connection.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name IN ('authenticated_sessions','token_replay_records','session_security_events')"))}
    assert not {"token", "raw_token", "jwt", "payload", "password", "secret"}.intersection(columns)

@pytest.mark.integration
def test_atomic_single_use_jti_concurrent_replay_allows_one_success():
    _, _, _, service, context, value = setup(); barrier = Barrier(2); lock = Lock(); outcomes = []
    jti = "jti-concurrent-" + uuid4().hex
    def invoke():
        with TenantContextBinder().bind_tenant(context):
            barrier.wait()
            try: service.validate(SessionValidationRequest(value, jti, "SINGLE_USE", "corr")); result = "OK"
            except SessionValidationRejected: result = "REPLAY"
            with lock: outcomes.append(result)
    threads = [Thread(target=invoke) for _ in range(2)]
    for item in threads: item.start()
    for item in threads: item.join()
    assert sorted(outcomes) == ["OK", "REPLAY"]

@pytest.mark.integration
def test_runtime_rls_and_required_unique_jti_constraint():
    _, owner, engine, service, context, value = setup()
    with TenantContextBinder().bind_tenant(context):
        assert service.readiness().ready
        service.validate(SessionValidationRequest(value, "jti-rls-" + uuid4().hex, "ACCESS", "corr"))
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM authenticated_sessions")).scalar_one() == 0
    with owner.connect() as connection:
        unique = connection.execute(text("SELECT count(*) FROM pg_indexes WHERE tablename='token_replay_records' AND indexdef LIKE '%UNIQUE%'" )).scalar_one()
        rls = connection.execute(text("SELECT count(*) FROM pg_tables WHERE tablename IN ('authenticated_sessions','token_replay_records','session_security_events') AND rowsecurity=true")).scalar_one()
    assert unique >= 1 and rls == 3
