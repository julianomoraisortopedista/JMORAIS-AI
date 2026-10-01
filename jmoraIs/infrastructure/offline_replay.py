from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from time import monotonic
from uuid import uuid4

from sqlalchemy import create_engine, text

from jmoraIs.infrastructure.cryptographic_replay import (
    PostgreSQLCryptographicReplayEngine, ReplayIntegrityStatus,
)
from jmoraIs.secrets.domain import SecretPurpose


OFFLINE_REPLAY_ROLE = "jmorais_offline_replay_verifier"
OFFLINE_REPLAY_POLICY_VERSION = "offline-replay-v1"
REPLAY_TABLES = (
    "alembic_version",
    "canonical_ledger_claims", "canonical_ledger_supports", "canonical_ledger_events",
    "governed_clinical_audit_events", "clinical_conflict_adjudication_events",
    "governed_evidence_lifecycle_events", "governed_evidence_versions",
    "governed_evidence_persisted_references", "evidence_lifecycle_current",
    "evidence_package_catalog", "evidence_package_versions",
    "cryptographic_stream_checkpoints", "persisted_gateway_inputs",
    "governed_llm_drafts", "governed_llm_draft_lifecycle_events",
    "governed_llm_draft_persisted_references",
    "llm_invocation_persisted_references",
    "medical_document_persisted_references",
    "guideline_recommendation_set_references", "orthopedic_assessment_set_references",
    "human_review_persisted_references",
    "llm_invocations", "llm_invocation_contexts", "llm_human_review_events",
    "llm_human_review_security_events",
)


class OfflineReplayMode(str, Enum):
    STARTUP = "STARTUP"
    RELEASE = "RELEASE"
    DISASTER_RECOVERY = "DISASTER_RECOVERY"
    OFFLINE = "OFFLINE"


class OfflineReplayVerificationError(RuntimeError):
    pass


@dataclass(frozen=True)
class OfflineReplayRequest:
    mode: OfflineReplayMode
    release_id: str
    build_id: str
    source_revision: str
    migration_revision: str
    actor_id: str
    correlation_id: str


@dataclass(frozen=True)
class OfflineReplayResult:
    execution_id: str
    decision: ReplayIntegrityStatus
    verified_events: int
    failed_events: int
    broken_chains: int
    stream_count: int
    started_at: datetime
    completed_at: datetime
    duration_ms: float
    policy_version: str


@dataclass(frozen=True)
class OfflineReplayAuditEvent:
    execution_id: str
    mode: str
    release_id: str
    build_id: str
    source_revision: str
    migration_revision: str
    actor_id: str
    correlation_id: str
    verifier_role: str
    credential_provider: str
    credential_reference: str
    credential_version: str | None
    policy_version: str
    decision: str
    verified_events: int
    failed_events: int
    broken_chains: int
    stream_count: int
    failure_category: str | None
    started_at: datetime
    completed_at: datetime
    duration_ms: float
    disposal_status: str


class PostgreSQLOfflineReplayAudit:
    def __init__(self, engine): self._engine = engine
    def append(self, value: OfflineReplayAuditEvent) -> None:
        with self._engine.begin() as connection:
            connection.execute(text("""INSERT INTO offline_replay_verifier_events
              (execution_id,mode,release_id,build_id,source_revision,migration_revision,actor_id,
               correlation_id,verifier_role,credential_provider,credential_reference,credential_version,
               policy_version,decision,verified_events,failed_events,broken_chains,stream_count,
               failure_category,started_at,completed_at,duration_ms,disposal_status)
              VALUES(:execution_id,:mode,:release_id,:build_id,:source_revision,:migration_revision,:actor_id,
               :correlation_id,:verifier_role,:credential_provider,:credential_reference,:credential_version,
               :policy_version,:decision,:verified_events,:failed_events,:broken_chains,:stream_count,
               :failure_category,:started_at,:completed_at,:duration_ms,:disposal_status)"""), value.__dict__)


class _PinnedEngine:
    def __init__(self, connection, dialect): self._connection, self.dialect = connection, dialect
    def connect(self): return nullcontext(self._connection)


class OfflineReplayVerifier:
    """Ephemeral global verifier. Instances and pools must never enter API dependencies."""
    def __init__(self, secrets, credential_reference, audit, *, clock=None,
                 role=OFFLINE_REPLAY_ROLE, pool_observer=None, require_tls=False):
        if credential_reference.purpose is not SecretPurpose.OFFLINE_REPLAY_DATABASE_CREDENTIAL:
            raise OfflineReplayVerificationError("offline replay credential purpose is invalid")
        self._secrets, self._reference, self._audit = secrets, credential_reference, audit
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._role, self._pool_observer, self._require_tls = role, pool_observer, require_tls

    def verify(self, request: OfflineReplayRequest) -> OfflineReplayResult:
        if not all((request.release_id, request.build_id, request.source_revision,
                    request.migration_revision, request.actor_id, request.correlation_id)):
            raise OfflineReplayVerificationError("complete offline replay attribution is required")
        execution_id = "replay_" + uuid4().hex
        started_at = self._clock(); started = monotonic(); engine = None
        report = None; failure = None; disposed = False
        try:
            engine = self._secrets.use_secret(
                self._reference, actor_id=request.actor_id,
                consumer=lambda raw: self._create_engine(raw.decode("utf-8")),
            )
            if self._pool_observer is not None: self._pool_observer(engine)
            with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
                with connection.begin():
                    connection.exec_driver_sql(f'SET LOCAL ROLE "{self._role}"')
                    connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                    self._validate_privileges(connection, request.migration_revision)
                    report = PostgreSQLCryptographicReplayEngine(
                        _PinnedEngine(connection, engine.dialect)).replay_all()
            decision = report.overall_decision
        except Exception as exc:
            failure = type(exc).__name__
            decision = ReplayIntegrityStatus.TAMPERED
        finally:
            if engine is not None:
                engine.dispose(); disposed = True
        completed_at = self._clock(); duration = round((monotonic() - started) * 1000, 3)
        value = OfflineReplayResult(execution_id, decision,
            report.verified_events if report else 0, report.failed_events if report else 1,
            report.broken_chains if report else 0, len(report.streams) if report else 0,
            started_at, completed_at, duration, OFFLINE_REPLAY_POLICY_VERSION)
        audit = OfflineReplayAuditEvent(execution_id, request.mode.value, request.release_id,
            request.build_id, request.source_revision, request.migration_revision, request.actor_id,
            request.correlation_id, self._role, self._reference.provider, self._reference.reference,
            self._reference.version, OFFLINE_REPLAY_POLICY_VERSION, decision.value,
            value.verified_events, value.failed_events, value.broken_chains, value.stream_count,
            failure, started_at, completed_at, duration, "DISPOSED" if disposed else "NOT_CREATED")
        try: self._audit.append(audit)
        except Exception as exc: raise OfflineReplayVerificationError("offline replay audit is unavailable") from exc
        if not disposed or decision is not ReplayIntegrityStatus.VALID:
            raise OfflineReplayVerificationError(
                "offline replay verification failed" if failure is None else "offline replay execution unavailable")
        return value

    def _create_engine(self, url):
        connect_args = {"connect_timeout": 10, "application_name": "jmorais-offline-replay-verifier",
            "options": "-c statement_timeout=120000 -c lock_timeout=5000 -c idle_in_transaction_session_timeout=120000"}
        if self._require_tls: connect_args["sslmode"] = "require"
        return create_engine(url, future=True, pool_size=1, max_overflow=0, pool_pre_ping=True,
            pool_timeout=10, connect_args=connect_args)

    def _validate_privileges(self, connection, revision):
        row = connection.execute(text("SELECT current_user, current_setting('transaction_read_only')" )).one()
        bypass = connection.execute(text("SELECT rolbypassrls FROM pg_roles WHERE rolname=current_user")).scalar_one()
        current_revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        if row[0] != self._role or row[1] != "on" or not bypass or current_revision != revision:
            raise OfflineReplayVerificationError("offline replay role or schema invariant failed")
        for table in REPLAY_TABLES:
            privileges = connection.execute(text("""SELECT
              has_table_privilege(current_user,:table,'SELECT'),
              has_table_privilege(current_user,:table,'INSERT,UPDATE,DELETE,TRUNCATE')"""), {"table": table}).one()
            if not privileges[0] or privileges[1]:
                raise OfflineReplayVerificationError("offline replay least-privilege invariant failed")
