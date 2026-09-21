from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional
from jmoraIs.clinical.governed import HumanReviewStatus
from jmoraIs.reasoning_input.exact_reference import PersistedClinicalReasoningInputReference

class OrthopedicBoundaryError(RuntimeError):pass
class OrthopedicVersionConflict(OrthopedicBoundaryError):pass
class AnatomicalScope(str,Enum):KNEE="KNEE";HIP="HIP";ANKLE="ANKLE";SHOULDER="SHOULDER";ELBOW="ELBOW";WRIST="WRIST";HAND="HAND";SPINE="SPINE";FOOT="FOOT"
class OrthopedicLaterality(str,Enum):RIGHT="RIGHT";LEFT="LEFT";BILATERAL="BILATERAL";MIDLINE="MIDLINE";NOT_APPLICABLE="NOT_APPLICABLE";UNKNOWN="UNKNOWN"
class FindingCategory(str,Enum):PAIN="PAIN";SWELLING="SWELLING";EFFUSION="EFFUSION";INSTABILITY="INSTABILITY";LOCKING="LOCKING";CATCHING="CATCHING";CREPITUS="CREPITUS";STIFFNESS="STIFFNESS";LIMITED_ROM="LIMITED_ROM";WEAKNESS="WEAKNESS";DEFORMITY="DEFORMITY";ALIGNMENT_ABNORMALITY="ALIGNMENT_ABNORMALITY";GAIT_ABNORMALITY="GAIT_ABNORMALITY";FUNCTIONAL_LIMITATION="FUNCTIONAL_LIMITATION"
class OrthopedicProblemStatus(str,Enum):DOCUMENTED="DOCUMENTED";SUSPECTED="SUSPECTED";CONFIRMED_BY_SOURCE="CONFIRMED_BY_SOURCE";HISTORICAL="HISTORICAL";POSTOPERATIVE="POSTOPERATIVE";RESOLVED="RESOLVED";REVIEW_REQUIRED="REVIEW_REQUIRED"
class Severity(str,Enum):MILD="MILD";MODERATE="MODERATE";SEVERE="SEVERE";UNKNOWN="UNKNOWN"
class ConcordanceStatus(str,Enum):CONCORDANT="CONCORDANT";PARTIALLY_CONCORDANT="PARTIALLY_CONCORDANT";DISCORDANT="DISCORDANT";INSUFFICIENT_DATA="INSUFFICIENT_DATA";REVIEW_REQUIRED="REVIEW_REQUIRED"
class GuidelineCorrelationStatus(str,Enum):APPLICABLE="APPLICABLE";PARTIALLY_APPLICABLE="PARTIALLY_APPLICABLE";NOT_APPLICABLE="NOT_APPLICABLE";CONFLICTING="CONFLICTING";REVIEW_REQUIRED="REVIEW_REQUIRED"
class AssessmentReadiness(str,Enum):READY_FOR_HUMAN_REVIEW="READY_FOR_HUMAN_REVIEW";REVIEW_REQUIRED="REVIEW_REQUIRED";INSUFFICIENT_DATA="INSUFFICIENT_DATA";CONFLICTING_DATA="CONFLICTING_DATA";BLOCKED="BLOCKED"
class OrthopedicAuditType(str,Enum):GENERATION="GENERATION";FINDING_CORRELATION="FINDING_CORRELATION";IMAGING_CORRELATION="IMAGING_CORRELATION";EVIDENCE_CORRELATION="EVIDENCE_CORRELATION";GUIDELINE_CORRELATION="GUIDELINE_CORRELATION";CONFLICT="CONFLICT";REVIEW_TRANSITION="REVIEW_TRANSITION";SUPERSESSION="SUPERSESSION";BLOCKED="BLOCKED"
def required(value,name):
    if not isinstance(value,str) or not value.strip():raise OrthopedicBoundaryError(f"{name} is required")
@dataclass(frozen=True)
class OrthopedicFindingReference:
    reference_id:str;concept_id:str;joint:AnatomicalScope;laterality:OrthopedicLaterality;category:FindingCategory;source:str;confidence:float;provenance:str;epistemic_status:str;severity:Severity=Severity.UNKNOWN;severity_scale_reference:Optional[str]=None
@dataclass(frozen=True)
class StabilityFindingReference:
    reference_id:str;test_concept_id:str;joint:AnatomicalScope;laterality:OrthopedicLaterality;finding:str;source:str;confidence:float;provenance:str;epistemic_status:str
@dataclass(frozen=True)
class ImagingFindingReference:
    reference_id:str;finding_concept_id:str;modality:str;joint:AnatomicalScope;laterality:OrthopedicLaterality;source:str;provenance:str
@dataclass(frozen=True)
class FunctionalReference:
    reference_id:str;gait:Optional[str];adls:tuple[str,...];work_limitations:tuple[str,...];sports_limitations:tuple[str,...];stairs:Optional[str];walking_distance:Optional[str];weight_bearing_tolerance:Optional[str];validated_score_reference:Optional[str];provenance:str
@dataclass(frozen=True)
class SurgicalHistoryReference:
    reference_id:str;procedure_concept_id:str;joint:AnatomicalScope;laterality:OrthopedicLaterality;procedure_date:Optional[datetime];revision_status:Optional[str];outcome_reference:Optional[str];provenance:str
@dataclass(frozen=True)
class ImplantStateReference:
    reference_id:str;implant_type_concept_id:str;joint:AnatomicalScope;laterality:OrthopedicLaterality;procedure_date:Optional[datetime];revision_status:Optional[str];provenance:str
@dataclass(frozen=True)
class GovernedOrthopedicStateView:
    state_reference_id:str;state_version:int;terminology_version:str;findings:tuple[OrthopedicFindingReference,...];stability_findings:tuple[StabilityFindingReference,...];imaging:tuple[ImagingFindingReference,...];functional:tuple[FunctionalReference,...];surgeries:tuple[SurgicalHistoryReference,...];implants:tuple[ImplantStateReference,...];quality_flags:tuple[str,...];provenance_references:tuple[str,...]
    subject_reference:str="";policy_version:str="MIP-07-PROJECTION-1";generated_at:Optional[datetime]=None;projection_version:int=1;predecessor_projection_reference:Optional[str]=None
@dataclass(frozen=True)
class MechanicalAssessment:
    finding_references:tuple[str,...];mechanical_symptom_references:tuple[str,...];instability_references:tuple[str,...];rom_limitation_references:tuple[str,...];weight_bearing_references:tuple[str,...];activity_related_references:tuple[str,...]
@dataclass(frozen=True)
class StabilityAssessment:
    examination_references:tuple[str,...];test_concept_ids:tuple[str,...];laterality:OrthopedicLaterality;quality_flags:tuple[str,...]
@dataclass(frozen=True)
class AlignmentAssessment:
    finding_references:tuple[str,...];laterality:OrthopedicLaterality
@dataclass(frozen=True)
class FunctionalAssessment:
    functional_references:tuple[str,...];gait:tuple[str,...];adls:tuple[str,...];work:tuple[str,...];sports:tuple[str,...];validated_score_references:tuple[str,...]
@dataclass(frozen=True)
class ImagingCorrelation:
    imaging_reference_id:str;clinical_finding_references:tuple[str,...];anatomical_concept_id:str;laterality:OrthopedicLaterality;status:ConcordanceStatus;quality_issues:tuple[str,...];provenance_references:tuple[str,...]
@dataclass(frozen=True)
class EvidenceCorrelation:
    problem_reference_id:str;supporting:tuple[str,...];opposing:tuple[str,...];neutral:tuple[str,...];inconclusive:tuple[str,...]
@dataclass(frozen=True)
class GuidelineCorrelation:
    recommendation_id:str;status:GuidelineCorrelationStatus;guideline_id:str;guideline_version:str;strength_reference:str;conflict_references:tuple[str,...]
@dataclass(frozen=True)
class OrthopedicProblemAssessment:
    problem_id:str;joint:AnatomicalScope;laterality:OrthopedicLaterality;status:OrthopedicProblemStatus;severity:Severity;finding_references:tuple[str,...];terminology_concept_ids:tuple[str,...];evidence:EvidenceCorrelation;guidelines:tuple[GuidelineCorrelation,...];limitations:tuple[str,...]
@dataclass(frozen=True)
class JointAssessment:
    joint:AnatomicalScope;laterality:OrthopedicLaterality;problems:tuple[OrthopedicProblemAssessment,...];mechanical:MechanicalAssessment;stability:StabilityAssessment;alignment:AlignmentAssessment;functional:FunctionalAssessment;imaging:tuple[ImagingCorrelation,...];surgery_references:tuple[str,...];implant_references:tuple[str,...];quality_flags:tuple[str,...]
@dataclass(frozen=True)
class OrthopedicConfidence:
    source_completeness:float;terminology_certainty:float;examination_completeness:float;imaging_concordance:float;evidence_availability:float;guideline_applicability:float;conflict_burden:float;policy_version:str
@dataclass(frozen=True)
class OrthopedicAssessment:
    assessment_id:str;reasoning_input_id:str;reasoning_input_version:int;clinical_state_reference_id:str;clinical_state_version:int;terminology_version:str;joints:tuple[JointAssessment,...];governed_evidence_ids:tuple[str,...];guideline_recommendation_ids:tuple[str,...];quality_flags:tuple[str,...];missing_data:tuple[str,...];limitations:tuple[str,...];confidence:OrthopedicConfidence;readiness:AssessmentReadiness;review_status:HumanReviewStatus;externally_actionable:bool;policy_version:str;generated_at:datetime;provenance_references:tuple[str,...]
@dataclass(frozen=True)
class OrthopedicAssessmentSet:
    set_id:str;subject_reference:str;set_version:int;previous_set_id:Optional[str];assessment:OrthopedicAssessment;review_status:HumanReviewStatus;generated_at:datetime
    clinical_reasoning_input_reference:Optional[PersistedClinicalReasoningInputReference]=None
    @property
    def reasoning_lineage_status(self):return "EXACT" if self.clinical_reasoning_input_reference else "LEGACY_MISSING_CLINICAL_REASONING_INPUT_REFERENCE"
@dataclass(frozen=True)
class PersistedOrthopedicAssessmentSetReference:
    reference_id:str;set_id:str;set_version:int;subject_reference:str;tenant_id:str;policy_version:str;integrity_hash:str;issued_at:datetime
@dataclass(frozen=True)
class OrthopedicAuditEvent:
    event_id:str;subject_reference:str;set_id:str;event_type:OrthopedicAuditType;occurred_at:datetime;actor_id:str;decision_code:str;reference_ids:tuple[str,...];policy_version:str
