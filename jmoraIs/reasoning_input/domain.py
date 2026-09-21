from __future__ import annotations
from dataclasses import dataclass
from datetime import date,datetime
from enum import Enum
from typing import Optional
from jmoraIs.terminology.domain import PersistedTerminologyMappingGovernanceReference
from jmoraIs.clinical_state.exact_reference import PersistedClinicalStateReference
from jmoraIs.appraisal.exact_reference import PersistedGovernedEvidenceReference

class ReasoningInputError(RuntimeError):pass
class ReasoningInputVersionConflict(ReasoningInputError):pass
class InvalidReasoningInput(ReasoningInputError):pass

class ReasoningReviewStatus(str,Enum):
    AUTO_ASSEMBLED="AUTO_ASSEMBLED";REVIEW_REQUIRED="REVIEW_REQUIRED";REVIEWED="REVIEWED";APPROVED="APPROVED";REJECTED="REJECTED"
class ReasoningReadiness(str,Enum):
    READY_FOR_REASONING="READY_FOR_REASONING";BLOCKED="BLOCKED";INSUFFICIENT_DATA="INSUFFICIENT_DATA";CONFLICTING_INPUT="CONFLICTING_INPUT";REVIEW_REQUIRED="REVIEW_REQUIRED"
class EvidenceDirection(str,Enum):
    SUPPORTING="SUPPORTING";OPPOSING="OPPOSING";NEUTRAL="NEUTRAL";INCONCLUSIVE="INCONCLUSIVE"
class ReasoningAuditType(str,Enum):
    CREATION="CREATION";VALIDATION="VALIDATION";RECONSTRUCTION="RECONSTRUCTION";APPROVAL="APPROVAL";REJECTION="REJECTION"

def _required(value,name):
    if not isinstance(value,str) or not value.strip():raise InvalidReasoningInput(f"{name} is required")
def _aware(value,name):
    if value.tzinfo is None:raise InvalidReasoningInput(f"{name} must be timezone-aware")

@dataclass(frozen=True)
class TraceableReference:
    reference_id:str;origin:str;author:str;recorded_at:datetime;policy_version:str
    def __post_init__(self):
        for value,name in ((self.reference_id,"reference_id"),(self.origin,"origin"),(self.author,"author"),(self.policy_version,"policy_version")):_required(value,name)
        _aware(self.recorded_at,"recorded_at")

@dataclass(frozen=True)
class PatientClinicalStateReference(TraceableReference):
    patient_context_version:int;clinical_state_version:int
    def __post_init__(self):
        super().__post_init__()
        if self.patient_context_version<1 or self.clinical_state_version<1:raise InvalidReasoningInput("clinical reference versions must be positive")
@dataclass(frozen=True)
class GovernedEvidenceReference(TraceableReference):
    evidence_package_reference_id:str;direction:EvidenceDirection
@dataclass(frozen=True)
class EvidencePackageReference(TraceableReference):pass
@dataclass(frozen=True)
class TimelineReference(TraceableReference):pass
@dataclass(frozen=True)
class AuditReference(TraceableReference):pass
@dataclass(frozen=True)
class PolicyVersionReference(TraceableReference):
    policy_name:str
@dataclass(frozen=True)
class GuidelineReference(TraceableReference):
    guideline_version:str;organization:str;publication_date:date;strength:str;status:str;applicability:tuple[str,...]
    def __post_init__(self):
        super().__post_init__()
        for value,name in ((self.guideline_version,"guideline_version"),(self.organization,"organization"),(self.strength,"strength"),(self.status,"status")):_required(value,name)
        if not self.applicability:raise InvalidReasoningInput("guideline applicability is required")

@dataclass(frozen=True)
class DataQualitySummary:
    missing_data_references:tuple[str,...];conflicting_data_references:tuple[str,...];stale_data_references:tuple[str,...]
    review_required:bool;mapping_confidence:float;terminology_confidence:float;overall_input_completeness:float
    def __post_init__(self):
        for value,name in ((self.mapping_confidence,"mapping_confidence"),(self.terminology_confidence,"terminology_confidence"),(self.overall_input_completeness,"overall_input_completeness")):
            if not 0<=value<=1:raise InvalidReasoningInput(f"{name} must be between 0 and 1")

@dataclass(frozen=True)
class EvidenceReferenceSummary:
    supporting:tuple[GovernedEvidenceReference,...]=();opposing:tuple[GovernedEvidenceReference,...]=()
    neutral:tuple[GovernedEvidenceReference,...]=();inconclusive:tuple[GovernedEvidenceReference,...]=()
    def __post_init__(self):
        groups=((self.supporting,EvidenceDirection.SUPPORTING),(self.opposing,EvidenceDirection.OPPOSING),(self.neutral,EvidenceDirection.NEUTRAL),(self.inconclusive,EvidenceDirection.INCONCLUSIVE))
        if any(item.direction is not expected for items,expected in groups for item in items):raise InvalidReasoningInput("evidence direction does not match summary group")
        identifiers=[item.reference_id for items,_ in groups for item in items]
        if len(identifiers)!=len(set(identifiers)):raise InvalidReasoningInput("governed evidence references must be unique")
    @property
    def all(self):return self.supporting+self.opposing+self.neutral+self.inconclusive

@dataclass(frozen=True)
class ClinicalReasoningInput:
    input_id:str;subject_reference:str;input_version:int;previous_input_id:Optional[str];created_at:datetime
    patient_clinical_state:PatientClinicalStateReference;terminology_version:str
    evidence:EvidenceReferenceSummary;evidence_packages:tuple[EvidencePackageReference,...]
    applicable_guidelines:tuple[GuidelineReference,...];timeline:TimelineReference;review_status:ReasoningReviewStatus
    readiness:ReasoningReadiness;quality:DataQualitySummary;provenance_references:tuple[TraceableReference,...]
    audit_references:tuple[AuditReference,...];policy_versions:tuple[PolicyVersionReference,...]
    terminology_governance_references:tuple[PersistedTerminologyMappingGovernanceReference,...]=()
    clinical_state_reference:Optional[PersistedClinicalStateReference]=None
    governed_evidence_references:tuple[PersistedGovernedEvidenceReference,...]=()
    def __post_init__(self):
        for value,name in ((self.input_id,"input_id"),(self.subject_reference,"subject_reference"),(self.terminology_version,"terminology_version")):_required(value,name)
        _aware(self.created_at,"created_at")
        if self.input_version<1:raise InvalidReasoningInput("input version must be positive")
        if self.input_version==1 and self.previous_input_id is not None:raise InvalidReasoningInput("genesis input cannot have predecessor")
        if self.input_version>1 and not self.previous_input_id:raise InvalidReasoningInput("later input requires predecessor")
        if not self.provenance_references or not self.audit_references or not self.policy_versions:raise InvalidReasoningInput("provenance, audit, and policy references are mandatory")
        reference_ids=[item.reference_id for item in self.terminology_governance_references]
        if len(reference_ids)!=len(set(reference_ids)) or tuple(reference_ids)!=tuple(sorted(reference_ids)):raise InvalidReasoningInput("terminology governance references must be unique and deterministically ordered")
        evidence_reference_ids=[item.reference_id for item in self.governed_evidence_references]
        if len(evidence_reference_ids)!=len(set(evidence_reference_ids)) or tuple(evidence_reference_ids)!=tuple(sorted(evidence_reference_ids)):raise InvalidReasoningInput("exact governed evidence references must be unique and deterministically ordered")
        exact_members=(self.clinical_state_reference is not None,bool(self.governed_evidence_references),bool(self.terminology_governance_references))
        if any(exact_members[:2]) and not all(exact_members):raise InvalidReasoningInput("exact upstream lineage must be complete")
        package_ids=[item.reference_id for item in self.evidence_packages]
        if len(package_ids)!=len(set(package_ids)):raise InvalidReasoningInput("EvidencePackage references must be unique")
        if any(item.evidence_package_reference_id not in package_ids for item in self.evidence.all):raise InvalidReasoningInput("governed evidence must link to a referenced EvidencePackage")
        guideline_ids=[item.reference_id for item in self.applicable_guidelines]
        if len(guideline_ids)!=len(set(guideline_ids)):raise InvalidReasoningInput("guideline references must be unique")
    @property
    def terminology_lineage_status(self):
        return ReasoningTerminologyLineageStatus.EXACT if self.terminology_governance_references else ReasoningTerminologyLineageStatus.LEGACY_MISSING_EXACT_TERMINOLOGY_GOVERNANCE_REFERENCE
    @property
    def exact_upstream_lineage_status(self):
        return ReasoningUpstreamLineageStatus.EXACT if self.clinical_state_reference and self.governed_evidence_references and self.terminology_governance_references else ReasoningUpstreamLineageStatus.LEGACY_MISSING_PERSISTED_CLINICAL_REASONING_INPUT_REFERENCE

@dataclass(frozen=True)
class ReasoningInputValidation:
    input_id:str;valid:bool;readiness:ReasoningReadiness;issues:tuple[str,...];validated_at:datetime
@dataclass(frozen=True)
class ReasoningInputAuditEvent:
    event_id:str;subject_reference:str;input_id:str;event_type:ReasoningAuditType;occurred_at:datetime
    actor_id:str;source_reference:str;policy_version:str;decision_code:str

class ReasoningTerminologyLineageStatus(str,Enum):EXACT="EXACT";LEGACY_MISSING_EXACT_TERMINOLOGY_GOVERNANCE_REFERENCE="LEGACY_MISSING_EXACT_TERMINOLOGY_GOVERNANCE_REFERENCE"
class ReasoningUpstreamLineageStatus(str,Enum):EXACT="EXACT";LEGACY_MISSING_PERSISTED_CLINICAL_REASONING_INPUT_REFERENCE="LEGACY_MISSING_PERSISTED_CLINICAL_REASONING_INPUT_REFERENCE"
