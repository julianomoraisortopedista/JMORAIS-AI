from __future__ import annotations
from dataclasses import dataclass
from datetime import date,datetime
from enum import Enum
from typing import Optional
from jmoraIs.appraisal.domain import RecommendationStrength
from jmoraIs.clinical.governed import HumanReviewStatus

class GuidelineEngineError(RuntimeError):pass
class GuidelineBoundaryRejected(GuidelineEngineError):pass
class RecommendationVersionConflict(GuidelineEngineError):pass
class RecommendationIntent(str,Enum):RECOMMEND="RECOMMEND";CONSIDER="CONSIDER";DO_NOT_RECOMMEND="DO_NOT_RECOMMEND";AVOID="AVOID";INSUFFICIENT_EVIDENCE="INSUFFICIENT_EVIDENCE";NO_APPLICABLE_GUIDELINE="NO_APPLICABLE_GUIDELINE";CONFLICTING_GUIDANCE="CONFLICTING_GUIDANCE"
class RecommendationReadiness(str,Enum):READY_FOR_HUMAN_REVIEW="READY_FOR_HUMAN_REVIEW";REVIEW_REQUIRED="REVIEW_REQUIRED";BLOCKED="BLOCKED";INSUFFICIENT_EVIDENCE="INSUFFICIENT_EVIDENCE";CONFLICTING_GUIDANCE="CONFLICTING_GUIDANCE";NO_APPLICABLE_GUIDELINE="NO_APPLICABLE_GUIDELINE"
class ConflictSeverity(str,Enum):NO_CONFLICT="NO_CONFLICT";MINOR_CONFLICT="MINOR_CONFLICT";MATERIAL_CONFLICT="MATERIAL_CONFLICT";CRITICAL_CONFLICT="CRITICAL_CONFLICT"
class ApplicabilityOutcome(str,Enum):APPLICABLE="APPLICABLE";NOT_APPLICABLE="NOT_APPLICABLE";REVIEW_REQUIRED="REVIEW_REQUIRED"
class ContraindicationStatus(str,Enum):PRESENT="PRESENT";ABSENT="ABSENT";UNKNOWN="UNKNOWN"
class RecommendationAuditType(str,Enum):APPLICABILITY="APPLICABILITY";GENERATION="GENERATION";RANKING="RANKING";CONFLICT="CONFLICT";EVIDENCE_EXCLUDED="EVIDENCE_EXCLUDED";TERMINOLOGY_UNCERTAINTY="TERMINOLOGY_UNCERTAINTY";HUMAN_REVIEW="HUMAN_REVIEW";SUPERSESSION="SUPERSESSION";BLOCKED="BLOCKED"
def req(value,name):
    if not isinstance(value,str) or not value.strip():raise GuidelineBoundaryRejected(f"{name} is required")
@dataclass(frozen=True)
class ApplicabilityCriteria:
    population_contexts:tuple[str,...];required_concept_ids:tuple[str,...];contraindication_concept_ids:tuple[str,...]=()
    age_min:Optional[int]=None;age_max:Optional[int]=None;sex:Optional[str]=None;care_setting:Optional[str]=None;stage:Optional[str]=None
@dataclass(frozen=True)
class GovernedGuidelineRecommendation:
    guideline_recommendation_id:str;guideline_id:str;guideline_version:str;organization:str;statement:str;intent:RecommendationIntent
    strength:RecommendationStrength;evidence_certainty:str;methodological_quality:str;authority_weight:float;applicability:ApplicabilityCriteria
    governed_evidence_ids:tuple[str,...];publication_date:date;effective_date:date;expiration_date:Optional[date];withdrawn_at:Optional[date]
    superseded_by:Optional[str];appraisal_approved:bool;appraisal_version:str;terminology_version:str;policy_version:str;provenance_references:tuple[str,...]
    def __post_init__(self):
        for value,name in ((self.guideline_recommendation_id,"guideline recommendation"),(self.guideline_id,"guideline"),(self.guideline_version,"guideline version"),(self.organization,"organization"),(self.statement,"governed statement"),(self.appraisal_version,"appraisal version"),(self.policy_version,"policy version")) :req(value,name)
        if not self.governed_evidence_ids or not self.provenance_references:raise GuidelineBoundaryRejected("governed evidence and provenance are required")
        if not 0<=self.authority_weight<=1:raise GuidelineBoundaryRejected("authority weight must be explicit between 0 and 1")
@dataclass(frozen=True)
class GovernedGuidelineRecord:
    record_id:str;guideline_id:str;source_version_identifier:str;record_version:int;predecessor_record_id:Optional[str]
    governance_status:str;guideline:GovernedGuidelineRecommendation;appraisal_reference:str;appraisal_version:str
    provenance_references:tuple[str,...];policy_version:str;created_at:datetime
    def __post_init__(self):
        for value,name in ((self.record_id,"record"),(self.guideline_id,"guideline"),(self.source_version_identifier,"source version"),(self.governance_status,"governance status"),(self.appraisal_reference,"appraisal reference"),(self.appraisal_version,"appraisal version"),(self.policy_version,"policy version")):req(value,name)
        if self.record_version<1 or (self.record_version==1 and self.predecessor_record_id is not None):raise GuidelineBoundaryRejected("guideline source version chain is invalid")
        if self.guideline.guideline_id!=self.guideline_id or self.guideline.guideline_version!=self.source_version_identifier:raise GuidelineBoundaryRejected("guideline source identity mismatch")
        if self.guideline.appraisal_version!=self.appraisal_version or not self.provenance_references:raise GuidelineBoundaryRejected("appraisal and provenance linkage are required")
@dataclass(frozen=True)
class RecommendationApplicability:
    outcome:ApplicabilityOutcome;matched_contexts:tuple[str,...];matched_concept_ids:tuple[str,...];missing_factors:tuple[str,...];contraindication_status:ContraindicationStatus
@dataclass(frozen=True)
class RecommendationConflict:
    conflict_id:str;severity:ConflictSeverity;guideline_ids:tuple[str,...];dimensions:tuple[str,...];resolved:bool=False
@dataclass(frozen=True)
class RecommendationBasis:
    governed_evidence_ids:tuple[str,...];supporting:tuple[str,...];opposing:tuple[str,...];neutral:tuple[str,...];inconclusive:tuple[str,...]
@dataclass(frozen=True)
class RecommendationConfidence:
    input_completeness:float;evidence_quality:float;guideline_quality:float;applicability:float;terminology_confidence:float;conflict_burden:float;aggregate:float;policy_version:str
@dataclass(frozen=True)
class RecommendationExplanation:
    guideline_id:str;guideline_version:str;organization:str;strength:RecommendationStrength;evidence_certainty:str;appraisal_quality:str
    applicability:RecommendationApplicability;terminology_concept_ids:tuple[str,...];basis:RecommendationBasis;conflicts:tuple[RecommendationConflict,...]
    contraindication_status:ContraindicationStatus;limitations:tuple[str,...];data_quality_flags:tuple[str,...];human_review_status:HumanReviewStatus
@dataclass(frozen=True)
class GuidelineRecommendation:
    recommendation_id:str;guideline_recommendation_id:str;statement:str;intent:RecommendationIntent;rank:int;ranking_score:float
    reasoning_input_id:str;reasoning_input_version:int;governed_evidence_ids:tuple[str,...];guideline_id:str;guideline_version:str
    terminology_versions:tuple[str,...];applicable_concept_ids:tuple[str,...];appraisal_version:str;policy_version:str
    readiness:RecommendationReadiness;review_status:HumanReviewStatus;externally_actionable:bool;confidence:RecommendationConfidence
    explanation:RecommendationExplanation;provenance_references:tuple[str,...];generated_at:datetime
@dataclass(frozen=True)
class GuidelineRecommendationSet:
    set_id:str;subject_reference:str;set_version:int;previous_set_id:Optional[str];reasoning_input_id:str;recommendations:tuple[GuidelineRecommendation,...]
    readiness:RecommendationReadiness;review_status:HumanReviewStatus;policy_version:str;generated_at:datetime;provenance_references:tuple[str,...]
@dataclass(frozen=True)
class PersistedGuidelineRecommendationSetReference:
    reference_id:str;set_id:str;set_version:int;subject_reference:str;tenant_id:str;policy_version:str;integrity_hash:str;issued_at:datetime
@dataclass(frozen=True)
class RecommendationAuditEvent:
    event_id:str;subject_reference:str;set_id:str;event_type:RecommendationAuditType;occurred_at:datetime;actor_id:str;decision_code:str;reference_ids:tuple[str,...];policy_version:str
