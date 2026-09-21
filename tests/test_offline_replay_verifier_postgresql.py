from datetime import datetime, timezone
import json
import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from jmoraIs.infrastructure.cryptographic_replay import ReplayIntegrityStatus
from jmoraIs.infrastructure.cryptographic_replay import PostgreSQLCryptographicReplayEngine
from jmoraIs.infrastructure.production_runtime import CURRENT_SCHEMA_REVISION
from jmoraIs.infrastructure.managed_secrets import EphemeralSecretProvider
from jmoraIs.infrastructure.offline_replay import (
    OFFLINE_REPLAY_ROLE, OfflineReplayMode, OfflineReplayRequest, OfflineReplayVerifier,
    OfflineReplayVerificationError,
    PostgreSQLOfflineReplayAudit, REPLAY_TABLES,
)
from jmoraIs.infrastructure.tenant_database import create_tenant_runtime_engine
from jmoraIs.secrets.domain import SecretPurpose, SecretReference
from tests.test_cryptographic_ledger_replay import stream

pytestmark = pytest.mark.integration
NOW = datetime(2026, 8, 16, tzinfo=timezone.utc)

@pytest.fixture(scope="module", autouse=True)
def isolated_database():
    url = os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url: yield; return
    owner = create_engine(url, future=True)
    with owner.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE")); connection.execute(text("CREATE SCHEMA public"))
    config = Config("alembic.ini"); config.set_main_option("sqlalchemy.url", url); command.upgrade(config, "head")
    yield
    with owner.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE")); connection.execute(text("CREATE SCHEMA public"))
    owner.dispose()


def _setup():
    url = os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url: pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    config = Config("alembic.ini"); config.set_main_option("sqlalchemy.url", url); command.upgrade(config, "head")
    owner = create_engine(url, future=True)
    runtime = create_tenant_runtime_engine(url, runtime_role="jmorais_application_writer")
    reference = SecretReference("test-managed", "offline-replay", SecretPurpose.OFFLINE_REPLAY_DATABASE_CREDENTIAL, "1")
    secrets = EphemeralSecretProvider({(reference.reference, reference.version): (reference, url.encode())})
    request = OfflineReplayRequest(OfflineReplayMode.RELEASE, "rc1", "build-rc1", "source-rc1",
        CURRENT_SCHEMA_REVISION, "release-verifier", "corr-offline-replay")
    return owner, runtime, reference, secrets, request


def test_offline_verifier_valid_visibility_privileges_audit_and_pool_disposal():
    owner, runtime, reference, secrets, request = _setup(); observed = []
    try:
        verifier = OfflineReplayVerifier(secrets, reference, PostgreSQLOfflineReplayAudit(runtime),
            clock=lambda: NOW, pool_observer=lambda engine: observed.append((engine, engine.pool)))
        result = verifier.verify(request)
        assert result.decision is ReplayIntegrityStatus.VALID
        assert len(observed) == 1 and observed[0][0].pool is not observed[0][1]
        with owner.connect() as connection:
            audit = connection.execute(text("SELECT decision,disposal_status,failure_category FROM offline_replay_verifier_events WHERE execution_id=:id"), {"id": result.execution_id}).one()
            role = connection.execute(text("SELECT rolbypassrls,rolcanlogin FROM pg_roles WHERE rolname=:role"), {"role": OFFLINE_REPLAY_ROLE}).one()
        assert audit == ("VALID", "DISPOSED", None)
        assert role == (True, False)
    finally:
        runtime.dispose(); owner.dispose()


def test_verifier_role_is_global_read_only_and_api_role_stays_tenant_scoped():
    owner, runtime, _, _, _ = _setup()
    try:
        with owner.connect() as connection:
            writer_bypass = connection.execute(text("SELECT rolbypassrls FROM pg_roles WHERE rolname='jmorais_application_writer'")).scalar_one()
            connection.execute(text(f'SET ROLE "{OFFLINE_REPLAY_ROLE}"'))
            assert all(connection.execute(text("SELECT has_table_privilege(current_user,:table,'SELECT')"), {"table": table}).scalar_one() for table in REPLAY_TABLES)
            assert not any(connection.execute(text("SELECT has_table_privilege(current_user,:table,'INSERT,UPDATE,DELETE,TRUNCATE')"), {"table": table}).scalar_one() for table in REPLAY_TABLES)
            with pytest.raises(Exception): connection.execute(text("CREATE TABLE offline_replay_forbidden(id integer)"))
        assert writer_bypass is False
    finally:
        runtime.dispose(); owner.dispose()


def test_offline_verifier_classifies_modified_payload_as_tampered_and_cleans_fixture():
    owner, runtime, reference, secrets, request = _setup(); claim_id = stream(owner, 2)
    try:
        with owner.connect() as connection:
            original = connection.execute(text("SELECT payload FROM canonical_ledger_events WHERE claim_id=:id AND stream_position=2"), {"id": claim_id}).scalar_one()
        with owner.begin() as connection:
            connection.execute(text("ALTER TABLE canonical_ledger_events DISABLE TRIGGER ALL"))
            connection.execute(text("UPDATE canonical_ledger_events SET payload=jsonb_set(payload,'{reason}','\"tampered\"'::jsonb) WHERE claim_id=:id AND stream_position=2"), {"id": claim_id})
            connection.execute(text("ALTER TABLE canonical_ledger_events ENABLE TRIGGER ALL"))
        verifier = OfflineReplayVerifier(secrets, reference, PostgreSQLOfflineReplayAudit(runtime), clock=lambda: NOW)
        with pytest.raises(OfflineReplayVerificationError, match="verification failed"):
            verifier.verify(request)
        with owner.connect() as connection:
            assert connection.execute(text("SELECT decision FROM offline_replay_verifier_events ORDER BY sequence_id DESC LIMIT 1")).scalar_one() == "TAMPERED"
    finally:
        with owner.begin() as connection:
            connection.execute(text("ALTER TABLE canonical_ledger_events DISABLE TRIGGER ALL"))
            connection.execute(text("UPDATE canonical_ledger_events SET payload=CAST(:payload AS jsonb) WHERE claim_id=:id AND stream_position=2"), {"payload": json.dumps(original), "id": claim_id})
            connection.execute(text("ALTER TABLE canonical_ledger_events ENABLE TRIGGER ALL"))
        runtime.dispose(); owner.dispose()


def test_offline_verifier_rejects_incomplete_checkpoint_and_cleans_fixture():
    owner, runtime, reference, secrets, request = _setup(); stream_id = "tenant-missing|pgi-missing"
    try:
        with owner.begin() as connection:
            connection.execute(text("""INSERT INTO cryptographic_stream_checkpoints
              (stream_namespace,stream_id,stream_position,head_hash,recorded_at)
              VALUES('persisted_gateway_inputs',:stream,1,:hash,:at)"""),
              {"stream": stream_id, "hash": "0" * 64, "at": NOW})
        assert PostgreSQLCryptographicReplayEngine(runtime).replay_all().overall_decision is ReplayIntegrityStatus.TAMPERED
        verifier = OfflineReplayVerifier(secrets, reference, PostgreSQLOfflineReplayAudit(runtime), clock=lambda: NOW)
        with pytest.raises(OfflineReplayVerificationError, match="verification failed"):
            verifier.verify(request)
    finally:
        with owner.begin() as connection:
            connection.execute(text("ALTER TABLE cryptographic_stream_checkpoints DISABLE TRIGGER ALL"))
            connection.execute(text("DELETE FROM cryptographic_stream_checkpoints WHERE stream_namespace='persisted_gateway_inputs' AND stream_id=:stream"), {"stream": stream_id})
            connection.execute(text("ALTER TABLE cryptographic_stream_checkpoints ENABLE TRIGGER ALL"))
        runtime.dispose(); owner.dispose()


def test_mandatory_audit_failure_fails_closed_after_pool_disposal():
    owner, runtime, reference, secrets, request = _setup(); observed = []
    class FailingAudit:
        def append(self, _value): raise RuntimeError("audit unavailable")
    try:
        verifier = OfflineReplayVerifier(secrets, reference, FailingAudit(), clock=lambda: NOW,
            pool_observer=lambda engine: observed.append((engine, engine.pool)))
        with pytest.raises(OfflineReplayVerificationError, match="audit"):
            verifier.verify(request)
        assert len(observed) == 1 and observed[0][0].pool is not observed[0][1]
    finally:
        runtime.dispose(); owner.dispose()
