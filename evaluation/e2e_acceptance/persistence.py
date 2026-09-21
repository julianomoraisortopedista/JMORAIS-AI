from __future__ import annotations
import json
from sqlalchemy import text
from .models import AcceptanceStage,E2ETraceManifest,ExecutionStatus,StageExecution

class PostgreSQLAcceptanceManifestRepository:
    """Validation-only manifest storage; never imported by production composition."""
    def __init__(self,engine):self._engine=engine
    def append(self,value:E2ETraceManifest):
        payload=[{"stage":x.stage.value,"status":x.status.value,"reference_id":x.reference_id,"version":x.version,
            "provenance_references":list(x.provenance_references),"occurred_at":x.occurred_at.isoformat(),"reason_code":x.reason_code} for x in value.stages]
        with self._engine.begin() as connection:
            connection.execute(text("""INSERT INTO e2e_acceptance_manifests
              (execution_id,case_id,tenant_id,correlation_id,stages,policy_versions,created_at)
              VALUES(:execution_id,:case_id,:tenant_id,:correlation_id,CAST(:stages AS jsonb),CAST(:policies AS jsonb),:created_at)"""),
              {**value.__dict__,"stages":json.dumps(payload),"policies":json.dumps(value.policy_versions)})
    def get(self,execution_id):
        with self._engine.connect() as connection:
            row=connection.execute(text("SELECT * FROM e2e_acceptance_manifests WHERE execution_id=:id"),{"id":execution_id}).mappings().first()
        if row is None:return None
        from datetime import datetime
        stages=tuple(StageExecution(AcceptanceStage(x["stage"]),ExecutionStatus(x["status"]),x["reference_id"],x["version"],
            tuple(x["provenance_references"]),datetime.fromisoformat(x["occurred_at"]),x["reason_code"]) for x in row["stages"])
        return E2ETraceManifest(row["execution_id"],row["case_id"],row["tenant_id"],row["correlation_id"],stages,
            tuple(row["policy_versions"]),row["created_at"])
