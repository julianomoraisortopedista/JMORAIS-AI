from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional
from jmoraIs.clinical.governed import HumanReviewStatus
from jmoraIs.scientific_domain import SupportDirection
from jmoraIs.medical_documents.exact_reference import PersistedMedicalDocumentVersionReference
class AuditDefenseError(RuntimeError):pass
class AuditDefenseBoundaryRejected(AuditDefenseError):pass
class AuditDefenseVersionConflict(AuditDefenseError):pass
class DefenseReferenceState(str,Enum):
    PRE_LINK="PRE_LINK"
    STAGE11_LINKED="STAGE11_LINKED"
class LegacyDefenseReference(AuditDefenseBoundaryRejected):pass
class DefenseStatus(str,Enum):DRAFT="DRAFT";REVIEW_REQUIRED="REVIEW_REQUIRED";UNDER_REVIEW="UNDER_REVIEW";APPROVED_BY_REVIEWER="APPROVED_BY_REVIEWER";REJECTED_BY_REVIEWER="REJECTED_BY_REVIEWER";SUPERSEDED="SUPERSEDED"
class ArgumentPosition(str,Enum):SUPPORTED="SUPPORTED";OPPOSED="OPPOSED";CONFLICTED="CONFLICTED";INSUFFICIENT="INSUFFICIENT";REVIEW_REQUIRED="REVIEW_REQUIRED"
class LimitationSeverity(str,Enum):INFORMATIONAL="INFORMATIONAL";MATERIAL="MATERIAL";CRITICAL="CRITICAL"
class AuditDefenseEventType(str,Enum):GENERATION="GENERATION";EVIDENCE_AGGREGATION="EVIDENCE_AGGREGATION";GUIDELINE_AGGREGATION="GUIDELINE_AGGREGATION";CONFLICT_EXPOSITION="CONFLICT_EXPOSITION";LIMITATION_EXPOSITION="LIMITATION_EXPOSITION";COUNTERARGUMENT_GENERATION="COUNTERARGUMENT_GENERATION";REVIEW_TRANSITION="REVIEW_TRANSITION";TRACE_LINKED="TRACE_LINKED";SUPERSESSION="SUPERSESSION";BLOCKED="BLOCKED"
@dataclass(frozen=True)
class MedicalDocumentVersionReference:
    document_stream_id:str;document_id:str;version:int;tenant_id:str;integrity_hash:str;policy_version:str
@dataclass(frozen=True)
class GovernedAuditClinicalFact:
    fact_id:str;clinical_state_reference_id:str;clinical_state_version:int;epistemic_status:str;terminology_concept_ids:tuple[str,...];provenance_references:tuple[str,...]
    pseudonymous_subject_reference:Optional[str]=None;fact_type:str="CLINICAL_FACT";source_reference_id:Optional[str]=None
    source:Optional[str]=None;policy_version:Optional[str]=None;recorded_at:Optional[datetime]=None
    quality_flags:tuple[str,...]=();review_status:Optional[str]=None
@dataclass(frozen=True)
class ScientificSupport:
    governed_evidence_id:str;evidence_package_id:str;direction:SupportDirection;evidence_level:str;methodological_quality:str;provenance_references:tuple[str,...];ledger_references:tuple[str,...]
@dataclass(frozen=True)
class GuidelineSupport:
    recommendation_id:str;guideline_id:str;guideline_version:str;organization:str;strength:str;review_status:HumanReviewStatus;conflict_references:tuple[str,...];limitation_references:tuple[str,...];provenance_references:tuple[str,...]
@dataclass(frozen=True)
class ClinicalSupport:
    fact_id:str;clinical_state_reference_id:str;clinical_state_version:int;epistemic_status:str;terminology_concept_ids:tuple[str,...];orthopedic_assessment_id:Optional[str];provenance_references:tuple[str,...]
@dataclass(frozen=True)
class Limitation:
    limitation_id:str;code:str;severity:LimitationSeverity;source_references:tuple[str,...];policy_version:str
@dataclass(frozen=True)
class CounterArgument:
    counterargument_id:str;code:str;source_references:tuple[str,...];evidence_directions:tuple[SupportDirection,...];limitations:tuple[str,...]
@dataclass(frozen=True)
class DefenseArgument:
    argument_id:str;argument_code:str;position:ArgumentPosition;clinical_support:tuple[ClinicalSupport,...];scientific_support:tuple[ScientificSupport,...];guideline_support:tuple[GuidelineSupport,...];counterarguments:tuple[CounterArgument,...];limitations:tuple[Limitation,...];terminology_references:tuple[str,...];policy_versions:tuple[str,...];provenance_references:tuple[str,...]
@dataclass(frozen=True)
class DefenseExplainability:
    supporting_evidence_ids:tuple[str,...];opposing_evidence_ids:tuple[str,...];neutral_evidence_ids:tuple[str,...];inconclusive_evidence_ids:tuple[str,...];guideline_recommendation_ids:tuple[str,...];clinical_fact_ids:tuple[str,...];conflict_references:tuple[str,...];limitation_ids:tuple[str,...];terminology_versions:tuple[str,...];policy_versions:tuple[str,...]
@dataclass(frozen=True)
class AuditDefense:
    defense_id:str;subject_reference:str;reasoning_input_id:str;reasoning_input_version:int;clinical_state_reference_id:str;clinical_state_version:int;orthopedic_assessment_set_id:str;orthopedic_assessment_version:int;arguments:tuple[DefenseArgument,...];explainability:DefenseExplainability;status:DefenseStatus;review_status:HumanReviewStatus;externally_actionable:bool;generated_at:datetime;provenance_references:tuple[str,...]
@dataclass(frozen=True)
class DefensePackage:
    package_id:str;stream_id:str;version:int;previous_package_id:Optional[str];defense:AuditDefense;reviewer_id:Optional[str];review_justification:Optional[str];created_at:datetime
    stage11_document_reference:Optional[MedicalDocumentVersionReference | PersistedMedicalDocumentVersionReference]=None
@dataclass(frozen=True)
class PersistedDefensePackageReference:
    reference_id:str;stream_id:str;version:int;package_id:str;tenant_id:str;policy_version:str
    integrity_hash:str;issued_at:datetime
    state:Optional[DefenseReferenceState]=None
@dataclass(frozen=True)
class AuditDefenseEvent:
    event_id:str;stream_id:str;package_id:str;event_type:AuditDefenseEventType;occurred_at:datetime;actor_id:str;decision_code:str;reference_ids:tuple[str,...];policy_version:str
