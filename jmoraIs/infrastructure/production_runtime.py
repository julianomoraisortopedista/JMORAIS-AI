from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import platform
from uuid import uuid4

from sqlalchemy import text

from jmoraIs.api.security import ReadinessCheck
from jmoraIs import __version__
CURRENT_SCHEMA_REVISION = "068_offline_medical_dependencies"


EXPECTED_APPEND_ONLY_TABLES = (
    "canonical_ledger_events", "evidence_package_catalog",
    "api_access_audit_events", "identity_security_events", "tenant_security_events",
    "session_security_events", "secret_security_events", "managed_key_state_events",
    "medical_document_versions", "medical_document_audit",
    "audit_defense_versions", "audit_defense_events", "audit_defense_persisted_references",
    "llm_prompt_versions", "llm_prompt_audit", "llm_invocations", "llm_invocation_contexts",
    "persisted_gateway_inputs", "cryptographic_stream_checkpoints",
    "governed_llm_drafts", "governed_llm_draft_lifecycle_events",
    "llm_human_review_events", "llm_human_review_security_events",
    "deployment_audit_events", "offline_replay_verifier_events",
    "patient_context_persisted_references",
    "clinical_state_persisted_references", "clinical_state_timeline_references",
    "clinical_state_timeline_reference_members", "governed_evidence_persisted_references",
    "governed_llm_draft_persisted_references",
    "llm_invocation_persisted_references",
    "medical_document_persisted_references",
    "human_review_persisted_references",
    "clinical_reasoning_input_persisted_references",
)


@dataclass(frozen=True)
class DeploymentAuditEvent:
    event_id: str
    release_id: str
    build_id: str
    source_revision: str
    application_version: str
    migration_revision: str
    python_version: str
    policy_versions: tuple[str, ...]
    provider_references: tuple[str, ...]
    occurred_at: datetime


class PostgreSQLDeploymentAudit:
    def __init__(self, engine): self._engine = engine
    def append(self, event: DeploymentAuditEvent):
        with self._engine.begin() as connection:
            connection.execute(text("""INSERT INTO deployment_audit_events
              (event_id,release_id,build_id,source_revision,application_version,migration_revision,
               python_version,policy_versions,provider_references,occurred_at)
              VALUES(:event_id,:release_id,:build_id,:source_revision,:application_version,:migration_revision,
               :python_version,CAST(:policy_versions AS jsonb),CAST(:provider_references AS jsonb),:occurred_at)"""), {**event.__dict__,
                "policy_versions": json.dumps(event.policy_versions),
                "provider_references": json.dumps(event.provider_references)})
    def readiness(self):
        try:
            with self._engine.connect() as connection: connection.execute(text("SELECT 1 FROM deployment_audit_events LIMIT 1"))
            return ReadinessCheck("deployment_audit", True, "AVAILABLE")
        except Exception: return ReadinessCheck("deployment_audit", False, "UNAVAILABLE")


class ProductionIntegrityVerifier:
    def __init__(self, engine, *, expected_revision=CURRENT_SCHEMA_REVISION):
        self._engine, self._expected_revision = engine, expected_revision
    def check(self):
        checks = []
        try:
            with self._engine.connect() as connection:
                revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                role = connection.execute(text("SELECT current_user")).scalar_one()
                bypass = connection.execute(text("SELECT rolbypassrls FROM pg_roles WHERE rolname=current_user")).scalar_one()
                triggers = set(connection.execute(text("SELECT event_object_table FROM information_schema.triggers WHERE trigger_name LIKE '%append_only%'" )).scalars())
            checks.extend((ReadinessCheck("production_migration", revision == self._expected_revision, revision),
                ReadinessCheck("production_runtime_role", role == "jmorais_application_writer" and not bypass,
                               "SAFE" if role == "jmorais_application_writer" and not bypass else "UNSAFE"),
                ReadinessCheck("append_only_triggers", set(EXPECTED_APPEND_ONLY_TABLES).issubset(triggers),
                               "ENFORCED" if set(EXPECTED_APPEND_ONLY_TABLES).issubset(triggers) else "MISSING")))
        except Exception:
            checks.append(ReadinessCheck("production_integrity", False, "UNAVAILABLE"))
        return tuple(checks)


def deployment_event(config, migration_revision: str):
    build = config.build_metadata
    references = tuple(sorted({x.provider + ":" + x.reference for x in
        (config.database_credential, *config.provider_secret_references) if x is not None}))
    return DeploymentAuditEvent("deploy_" + uuid4().hex, build.release_id, build.build_id,
        build.source_revision, __version__, migration_revision, platform.python_version(),
        (config.policy_version, config.oidc.policy_version, config.session_security.policy_version),
        references, datetime.now(timezone.utc))
