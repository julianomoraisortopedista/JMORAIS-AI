from __future__ import annotations

from hashlib import sha256

from jmoraIs.appraisal.application import clinical_appraisal_integrity_hash
from jmoraIs.appraisal.domain import AppraisalRecordStatus, ClinicalAppraisalRecord
from jmoraIs.clinical.governed import HumanReviewStatus
from jmoraIs.guideline_engine.application import GuidelineRecommendationEngine, guideline_validity_issue
from jmoraIs.guideline_engine.domain import GuidelineRecommendationSet
from jmoraIs.reasoning_input.domain import ClinicalReasoningInput
from jmoraIs.terminology.domain import ClinicalConcept, TerminologyStatus

from .domain import AuditDefenseBoundaryRejected


class PostgreSQLGovernedAuditGuidelineAdapter:
    """Restart-safe validation projection over canonical guideline repositories."""

    def __init__(self, recommendations, sources, reasoning_inputs, appraisals, terminology, *, clock):
        self._recommendations = recommendations
        self._sources = sources
        self._reasoning_inputs = reasoning_inputs
        self._appraisals = appraisals
        self._terminology = terminology
        self._clock = clock

    def latest(self, subject_reference):
        value = self._recommendations.latest(subject_reference)
        if not isinstance(value, GuidelineRecommendationSet):
            raise AuditDefenseBoundaryRejected("persisted GuidelineRecommendationSet is required")
        if value.subject_reference != subject_reference or not value.provenance_references:
            raise AuditDefenseBoundaryRejected("guideline recommendation set identity is invalid")
        self._validate_history(value)
        reasoning_input = self._reasoning_inputs.get(value.reasoning_input_id)
        if (not isinstance(reasoning_input, ClinicalReasoningInput)
                or reasoning_input.input_id != value.reasoning_input_id
                or reasoning_input.subject_reference != subject_reference):
            raise AuditDefenseBoundaryRejected("ClinicalReasoningInput linkage is invalid")
        if value.policy_version != GuidelineRecommendationEngine.RANKING_POLICY:
            raise AuditDefenseBoundaryRejected("recommendation-set policy version is invalid")
        if value.review_status is HumanReviewStatus.REJECTED_BY_REVIEWER:
            raise AuditDefenseBoundaryRejected("rejected guideline recommendation set is ineligible")
        for recommendation in value.recommendations:
            self._validate_recommendation(recommendation, reasoning_input)
        return value

    def _validate_history(self, current):
        history = self._recommendations.history(current.subject_reference)
        if not history or history[-1] != current:
            raise AuditDefenseBoundaryRejected("guideline recommendation history is incomplete")
        previous = None
        for position, value in enumerate(history, 1):
            if value.set_version != position or value.previous_set_id != (previous.set_id if previous else None):
                raise AuditDefenseBoundaryRejected("guideline recommendation version chain is invalid")
            generation = self._id(value.reasoning_input_id, str(value.set_version),
                                  *(item.recommendation_id for item in value.recommendations))
            review = self._id(previous.set_id, str(value.set_version), value.review_status.value) if previous else None
            if value.set_id not in {generation, review}:
                raise AuditDefenseBoundaryRejected("guideline recommendation set identifier is invalid")
            previous = value

    def _validate_recommendation(self, recommendation, reasoning_input):
        if (recommendation.reasoning_input_id != reasoning_input.input_id
                or recommendation.reasoning_input_version != reasoning_input.input_version):
            raise AuditDefenseBoundaryRejected("recommendation reasoning-input linkage is invalid")
        record = self._sources.current(recommendation.guideline_id)
        if record is None or record.guideline_id != recommendation.guideline_id:
            raise AuditDefenseBoundaryRejected("governed guideline source is missing")
        source = record.guideline
        if (record.governance_status != "ACTIVE"
                or record.source_version_identifier != recommendation.guideline_version
                or source.guideline_version != recommendation.guideline_version):
            raise AuditDefenseBoundaryRejected("governed guideline source version is ineligible")
        issue = guideline_validity_issue(source, reasoning_input, as_of=self._clock().date())
        if issue:
            raise AuditDefenseBoundaryRejected(f"governed guideline is ineligible: {issue}")
        appraisal = self._appraisals.get(record.appraisal_reference)
        if (not isinstance(appraisal, ClinicalAppraisalRecord)
                or appraisal.integrity_hash != clinical_appraisal_integrity_hash(appraisal)
                or appraisal.status is not AppraisalRecordStatus.ELIGIBLE
                or appraisal.framework_version != record.appraisal_version
                or appraisal.framework_version != recommendation.appraisal_version
                or not appraisal.provenance_references):
            raise AuditDefenseBoundaryRejected("guideline appraisal linkage is invalid")
        if (recommendation.policy_version != source.policy_version
                or recommendation.policy_version not in {item.policy_version for item in reasoning_input.policy_versions}
                or recommendation.terminology_versions != (reasoning_input.terminology_version,)
                or source.terminology_version != reasoning_input.terminology_version
                or not recommendation.provenance_references):
            raise AuditDefenseBoundaryRejected("guideline policy, terminology, or provenance linkage is invalid")
        for concept_id in recommendation.applicable_concept_ids:
            concept = self._terminology.latest(concept_id)
            if (not isinstance(concept, ClinicalConcept) or concept.status is not TerminologyStatus.ACTIVE
                    or concept.version != reasoning_input.terminology_version):
                raise AuditDefenseBoundaryRejected("guideline terminology reference is invalid")

    @staticmethod
    def _id(*parts):
        return "gr_" + sha256("|".join(parts).encode()).hexdigest()
