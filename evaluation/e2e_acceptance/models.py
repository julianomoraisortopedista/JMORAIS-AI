from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

class ExecutionStatus(str, Enum):
    NOT_STARTED="NOT_STARTED"; RUNNING="RUNNING"; BLOCKED="BLOCKED"
    REVIEW_REQUIRED="REVIEW_REQUIRED"; COMPLETED="COMPLETED"; FAILED="FAILED"

class AcceptanceStage(str, Enum):
    INGESTION="INGESTION"; PATIENT_CONTEXT="PATIENT_CONTEXT"; CLINICAL_STATE="CLINICAL_STATE"
    TERMINOLOGY="TERMINOLOGY"; EVIDENCE_PACKAGE="EVIDENCE_PACKAGE"; CLINICAL_APPRAISAL="CLINICAL_APPRAISAL"
    GOVERNED_EVIDENCE="GOVERNED_EVIDENCE"; REASONING_INPUT="REASONING_INPUT"
    GUIDELINE="GUIDELINE"; ORTHOPEDIC="ORTHOPEDIC"; DOCUMENT="DOCUMENT"; AUDIT_DEFENSE="AUDIT_DEFENSE"
    LLM_GATEWAY="LLM_GATEWAY"; HUMAN_REVIEW="HUMAN_REVIEW"

@dataclass(frozen=True)
class E2ECaseIdentity:
    execution_id:str; case_id:str; tenant_id:str; organization_id:str; principal_id:str
    purpose:str; correlation_id:str; policy_versions:tuple[str,...]; started_at:datetime
    def __post_init__(self):
        if not all((self.execution_id,self.case_id,self.tenant_id,self.organization_id,self.principal_id,self.purpose,self.correlation_id,self.policy_versions)):
            raise ValueError("complete de-identified E2E identity is required")

@dataclass(frozen=True)
class StageExecution:
    stage:AcceptanceStage; status:ExecutionStatus; reference_id:str|None; version:str|None
    provenance_references:tuple[str,...]; occurred_at:datetime; reason_code:str|None=None

@dataclass(frozen=True)
class E2ETraceManifest:
    execution_id:str; case_id:str; tenant_id:str; correlation_id:str
    stages:tuple[StageExecution,...]; policy_versions:tuple[str,...]; created_at:datetime
    @property
    def complete(self)->bool:
        expected=set(AcceptanceStage); completed={x.stage for x in self.stages if x.reference_id and x.version and x.provenance_references}
        return expected==completed and all(x.status in {ExecutionStatus.COMPLETED,ExecutionStatus.REVIEW_REQUIRED} for x in self.stages)

@dataclass(frozen=True)
class AcceptanceResult:
    identity:E2ECaseIdentity; status:ExecutionStatus; manifest:E2ETraceManifest
