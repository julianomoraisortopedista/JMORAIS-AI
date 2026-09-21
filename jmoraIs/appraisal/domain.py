from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum, IntEnum


class AppraisalInvariantError(ValueError):
    pass


class RiskOfBias(str, Enum):
    LOW = "LOW"
    SOME_CONCERNS = "SOME_CONCERNS"
    HIGH = "HIGH"
    UNCLEAR = "UNCLEAR"


class AssessmentRating(str, Enum):
    ADEQUATE = "ADEQUATE"
    PROBABLY_ADEQUATE = "PROBABLY_ADEQUATE"
    SOME_CONCERNS = "SOME_CONCERNS"
    INADEQUATE = "INADEQUATE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class MethodologicalQuality(str, Enum):
    HIGH = "HIGH"
    MODERATE = "MODERATE"
    LOW = "LOW"
    VERY_LOW = "VERY_LOW"


class EvidenceLevel(IntEnum):
    EXPERT_OPINION = 1
    CASE_REPORT = 2
    CASE_SERIES = 3
    CROSS_SECTIONAL = 4
    CASE_CONTROL = 5
    COHORT = 6
    RANDOMIZED_CONTROLLED_TRIAL = 7
    META_ANALYSIS = 8
    SYSTEMATIC_REVIEW = 9


class RecommendationStrength(IntEnum):
    STRONG_AGAINST = -2
    CONDITIONAL_AGAINST = -1
    NEUTRAL = 0
    CONDITIONAL_FOR = 1
    STRONG_FOR = 2


class ApplicabilityContext(str, Enum):
    ADULT = "ADULT"
    PEDIATRIC = "PEDIATRIC"
    GERIATRIC = "GERIATRIC"
    ATHLETE = "ATHLETE"
    PERIOPERATIVE = "PERIOPERATIVE"
    REHABILITATION = "REHABILITATION"
    OUTPATIENT = "OUTPATIENT"
    INPATIENT = "INPATIENT"


class GuidelineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"


class RecommendationValidity(str, Enum):
    VALID = "VALID"
    EXPIRED_GUIDELINE = "EXPIRED_GUIDELINE"
    SUPERSEDED_RECOMMENDATION = "SUPERSEDED_RECOMMENDATION"
    WITHDRAWN_RECOMMENDATION = "WITHDRAWN_RECOMMENDATION"


class ConflictType(str, Enum):
    RECOMMENDATION = "CONFLICTING_RECOMMENDATIONS"
    ORGANIZATION = "CONFLICTING_ORGANIZATIONS"
    PUBLICATION_DATE = "CONFLICTING_PUBLICATION_DATES"


_RATING_SCORE = {
    AssessmentRating.ADEQUATE: 1.0,
    AssessmentRating.PROBABLY_ADEQUATE: 0.75,
    AssessmentRating.SOME_CONCERNS: 0.5,
    AssessmentRating.INADEQUATE: 0.0,
}
_BIAS_SCORE = {
    RiskOfBias.LOW: 1.0,
    RiskOfBias.SOME_CONCERNS: 0.5,
    RiskOfBias.HIGH: 0.0,
    RiskOfBias.UNCLEAR: 0.25,
}


@dataclass(frozen=True)
class MethodologicalQualityAssessment:
    risk_of_bias: RiskOfBias
    randomization: AssessmentRating
    allocation_concealment: AssessmentRating
    blinding: AssessmentRating
    attrition: AssessmentRating
    selective_reporting: AssessmentRating
    external_validity: AssessmentRating
    statistical_robustness: AssessmentRating
    limitations: tuple[str, ...] = ()

    @property
    def score(self) -> float:
        values = [_BIAS_SCORE[self.risk_of_bias]]
        values.extend(
            _RATING_SCORE[value]
            for value in (
                self.randomization, self.allocation_concealment, self.blinding,
                self.attrition, self.selective_reporting, self.external_validity,
                self.statistical_robustness,
            )
            if value != AssessmentRating.NOT_APPLICABLE
        )
        return round(sum(values) / len(values), 4)

    @property
    def quality(self) -> MethodologicalQuality:
        if self.score >= 0.80:
            return MethodologicalQuality.HIGH
        if self.score >= 0.60:
            return MethodologicalQuality.MODERATE
        if self.score >= 0.35:
            return MethodologicalQuality.LOW
        return MethodologicalQuality.VERY_LOW


@dataclass(frozen=True)
class GuidelineGovernance:
    guideline_id: str
    issuing_organization: str
    publication_date: date
    revision_date: date | None
    expiration_date: date | None
    superseded_by_guideline_id: str | None
    withdrawn_at: date | None
    regional_applicability: tuple[str, ...]
    specialty_applicability: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.guideline_id.strip() or not self.issuing_organization.strip():
            raise AppraisalInvariantError("guideline identity and issuing organization are required")
        if self.revision_date and self.revision_date < self.publication_date:
            raise AppraisalInvariantError("revision date cannot precede publication")
        if self.expiration_date and self.expiration_date < self.publication_date:
            raise AppraisalInvariantError("expiration date cannot precede publication")
        if self.withdrawn_at and self.withdrawn_at < self.publication_date:
            raise AppraisalInvariantError("withdrawal date cannot precede publication")
        if not self.regional_applicability or not self.specialty_applicability:
            raise AppraisalInvariantError("regional and specialty applicability are required")

    def status(self, as_of: date) -> GuidelineStatus:
        if self.withdrawn_at and as_of >= self.withdrawn_at:
            return GuidelineStatus.WITHDRAWN
        if self.superseded_by_guideline_id:
            return GuidelineStatus.SUPERSEDED
        if self.expiration_date and as_of > self.expiration_date:
            return GuidelineStatus.EXPIRED
        return GuidelineStatus.ACTIVE


@dataclass(frozen=True)
class AppraisalRequest:
    recommendation_id: str
    topic_id: str
    recommendation: str
    evidence_package_id: str
    evidence_level: EvidenceLevel
    methodological_quality: MethodologicalQualityAssessment
    recommendation_strength: RecommendationStrength
    guideline: GuidelineGovernance
    applicability: tuple[ApplicabilityContext, ...]
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        required = (self.recommendation_id, self.topic_id, self.recommendation, self.evidence_package_id)
        if not all(value.strip() for value in required):
            raise AppraisalInvariantError("recommendation, topic and EvidencePackage linkage are required")
        if not self.applicability:
            raise AppraisalInvariantError("at least one applicability context is required")
        if len(self.applicability) != len(set(self.applicability)):
            raise AppraisalInvariantError("applicability contexts must be unique")


@dataclass(frozen=True)
class RecommendationExplainability:
    evidence_level: EvidenceLevel
    methodological_quality: MethodologicalQuality
    methodological_quality_score: float
    recommendation_strength: RecommendationStrength
    guideline_authority: str
    conflicts_detected: tuple[ConflictType, ...]
    applicability: tuple[ApplicabilityContext, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class AppraisedRecommendation:
    recommendation_id: str
    topic_id: str
    recommendation: str
    evidence_package_id: str
    recommendation_validity: RecommendationValidity
    eligible_for_clinical_intelligence: bool
    explainability: RecommendationExplainability
    provenance_references: tuple[str, ...]
    ledger_references: tuple[str, ...]
    policy_version: str

class AppraisalRecordStatus(str, Enum):
    ELIGIBLE="ELIGIBLE"; REVIEW_REQUIRED="REVIEW_REQUIRED"; SUPERSEDED="SUPERSEDED"

@dataclass(frozen=True)
class ClinicalAppraisalRecord:
    appraisal_id:str; evidence_package_id:str; recommendation_reference:str
    framework:str; framework_version:str; appraisal_version:int
    predecessor_appraisal_id:str|None; status:AppraisalRecordStatus
    appraisal:AppraisedRecommendation; source_request:AppraisalRequest
    provenance_references:tuple[str,...]; reviewer_reference:str|None; reviewer_status:str
    policy_version:str; created_at:datetime; superseded_by:str|None; integrity_hash:str
    def __post_init__(self):
        if not all((self.appraisal_id,self.evidence_package_id,self.recommendation_reference,self.framework,
                    self.framework_version,self.policy_version,self.provenance_references,self.integrity_hash)):
            raise AppraisalInvariantError("complete persisted appraisal attribution is required")
        if self.appraisal_version<1 or (self.appraisal_version==1 and self.predecessor_appraisal_id is not None):
            raise AppraisalInvariantError("appraisal version chain is invalid")
        if self.appraisal.evidence_package_id!=self.evidence_package_id or self.source_request.evidence_package_id!=self.evidence_package_id:
            raise AppraisalInvariantError("EvidencePackage linkage mismatch")


@dataclass(frozen=True)
class GuidelineConflict:
    conflict_type: ConflictType
    recommendation_ids: tuple[str, ...]
    details: str


@dataclass(frozen=True)
class GuidelineConflictResolution:
    conflicts: tuple[GuidelineConflict, ...]
    resolution_order: tuple[str, ...]


class GuidelineConflictResolver:
    """Detects disagreement and provides a transparent, deterministic review order."""

    def resolve(self, requests: tuple[AppraisalRequest, ...], as_of: date) -> GuidelineConflictResolution:
        conflicts: list[GuidelineConflict] = []
        for topic in sorted({item.topic_id for item in requests}):
            group = tuple(item for item in requests if item.topic_id == topic)
            if len(group) < 2:
                continue
            ids = tuple(sorted(item.recommendation_id for item in group))
            polarities = {self._polarity(item.recommendation_strength) for item in group}
            if "for" in polarities and "against" in polarities:
                conflicts.append(GuidelineConflict(ConflictType.RECOMMENDATION, ids,
                    f"Topic {topic} contains recommendations both for and against."))
            organizations = {item.guideline.issuing_organization for item in group}
            if len(organizations) > 1 and len(polarities) > 1:
                conflicts.append(GuidelineConflict(ConflictType.ORGANIZATION, ids,
                    "Organizations disagree: " + ", ".join(sorted(organizations))))
            dates = {item.guideline.publication_date for item in group}
            if len(dates) > 1 and len(polarities) > 1:
                conflicts.append(GuidelineConflict(ConflictType.PUBLICATION_DATE, ids,
                    "Conflicting recommendations were published on different dates."))

        ordered = sorted(requests, key=lambda item: (
            self._status_priority(item.guideline.status(as_of)),
            -item.evidence_level.value,
            -item.methodological_quality.score,
            -item.guideline.publication_date.toordinal(),
            item.recommendation_id,
        ))
        return GuidelineConflictResolution(tuple(conflicts), tuple(item.recommendation_id for item in ordered))

    @staticmethod
    def _polarity(strength: RecommendationStrength) -> str:
        return "for" if strength > 0 else "against" if strength < 0 else "neutral"

    @staticmethod
    def _status_priority(status: GuidelineStatus) -> int:
        return {GuidelineStatus.ACTIVE: 0, GuidelineStatus.EXPIRED: 1,
                GuidelineStatus.SUPERSEDED: 2, GuidelineStatus.WITHDRAWN: 3}[status]
