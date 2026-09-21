from __future__ import annotations

from sqlalchemy import text

from jmoraIs.api.security import ReadinessCheck
from jmoraIs.tenancy.domain import (
    Tenant, TenantSecurityEvent, TenantSecurityEventType, TenantStatus,
)


CANONICAL_TENANT_TABLES = (
    "patient_context_versions", "clinical_data_access_audit",
    "patient_clinical_state_versions", "clinical_state_audit_events",
    "clinical_reasoning_input_versions", "clinical_reasoning_input_audit",
    "governed_evidence_versions", "governed_evidence_lifecycle_events",
    "governed_clinical_audit_events", "clinical_conflict_adjudication_events",
    "guideline_recommendation_versions", "guideline_recommendation_audit",
    "orthopedic_assessment_versions", "orthopedic_assessment_audit",
    "medical_document_versions", "medical_document_audit",
    "audit_defense_versions", "audit_defense_events", "reviewer_identities",
    "external_identity_links", "api_access_audit_events", "llm_prompt_audit", "llm_invocations",
    "llm_invocation_contexts",
    "authenticated_sessions", "token_replay_records", "session_security_events",
)


class PostgreSQLTenantRepository:
    def __init__(self, engine): self._engine = engine

    def get(self, tenant_id: str):
        return self._one("tenant_id=:value", tenant_id)

    def resolve_organization(self, organization_id: str):
        return self._one("organization_id=:value", organization_id)

    def _one(self, predicate, value):
        with self._engine.connect() as connection:
            row = connection.execute(text("SELECT tenant_id,organization_id,display_name,status,"
                f"policy_version,created_at FROM tenants WHERE {predicate}"), {"value": value}).mappings().first()
        return None if row is None else Tenant(**{**dict(row), "status": TenantStatus(row["status"])})

    def readiness(self):
        try:
            with self._engine.connect() as connection: connection.execute(text("SELECT 1 FROM tenants LIMIT 1"))
            return ReadinessCheck("tenant_repository", True, "AVAILABLE")
        except Exception: return ReadinessCheck("tenant_repository", False, "UNAVAILABLE")


class PostgreSQLTenantSecurityAudit:
    def __init__(self, engine): self._engine = engine
    def append(self, event: TenantSecurityEvent):
        with self._engine.begin() as connection:
            connection.execute(text("""INSERT INTO tenant_security_events
                (event_id,event_type,tenant_id,organization_id,principal_id,correlation_id,
                 reason_code,policy_version,occurred_at)
                VALUES(:event_id,:event_type,:tenant_id,:organization_id,:principal_id,:correlation_id,
                 :reason_code,:policy_version,:occurred_at)"""),
                {**event.__dict__, "event_type": event.event_type.value})
    def history(self, correlation_id):
        with self._engine.connect() as connection:
            rows = connection.execute(text("SELECT event_id,event_type,tenant_id,organization_id,principal_id,"
                "correlation_id,reason_code,policy_version,occurred_at FROM tenant_security_events "
                "WHERE correlation_id=:id ORDER BY sequence_id"), {"id": correlation_id}).mappings().all()
        return tuple(TenantSecurityEvent(**{**dict(row), "event_type": TenantSecurityEventType(row["event_type"])})
                     for row in rows)


class PostgreSQLRLSReadiness:
    def __init__(self, engine, tables: tuple[str, ...]): self._engine, self._tables = engine, tables
    def readiness(self):
        try:
            with self._engine.connect() as connection:
                role = connection.execute(text("SELECT rolbypassrls FROM pg_roles WHERE rolname=current_user")).scalar_one()
                rows = connection.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' "
                    "AND rowsecurity=true AND tablename = ANY(:tables)"), {"tables": list(self._tables)}).scalars().all()
            ready = not role and set(rows) == set(self._tables)
            return ReadinessCheck("tenant_rls", ready, "ENFORCED" if ready else "NOT_ENFORCED")
        except Exception: return ReadinessCheck("tenant_rls", False, "UNAVAILABLE")
