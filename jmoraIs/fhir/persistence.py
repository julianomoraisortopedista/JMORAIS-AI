from __future__ import annotations

from sqlalchemy import text

from jmoraIs.patient_context.exact_reference import PersistedPatientContextReference
from jmoraIs.tenancy.context import current_tenant_context


class PostgreSQLFhirIdempotencyQueryAdapter:
    """Read-only projection over canonical ingestion and owner-issued reference metadata."""
    def __init__(self,engine):
        if engine.dialect.name!="postgresql": raise ValueError("FHIR idempotency requires PostgreSQL")
        self._engine=engine

    def find(self,source_reference_id):
        tenant=current_tenant_context()
        with self._engine.connect() as connection:
            row=connection.execute(text("""SELECT p.reference_id,p.context_id,p.context_version,
              p.pseudonymous_patient_id,p.tenant_id,p.policy_version,p.authorized_ingestion_record_id,
              p.context_integrity_hash,p.integrity_hash,p.issued_at
              FROM authorized_clinical_ingestion_records i
              JOIN patient_context_persisted_references p
                ON p.authorized_ingestion_record_id=i.ingestion_record_id AND p.tenant_id=i.tenant_id
              WHERE i.source_reference_id=:source AND i.tenant_id=:tenant"""),
              {"source":source_reference_id,"tenant":tenant.tenant_id}).mappings().all()
        if len(row)>1: raise RuntimeError("ambiguous canonical FHIR idempotency record")
        if not row:return None
        item=row[0]
        return PersistedPatientContextReference(item["reference_id"],item["context_id"],item["context_version"],
            item["pseudonymous_patient_id"],item["tenant_id"],item["policy_version"],
            item["authorized_ingestion_record_id"],item["context_integrity_hash"],item["integrity_hash"],item["issued_at"])
