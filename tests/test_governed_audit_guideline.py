from dataclasses import replace
from datetime import date

import pytest

from jmoraIs.audit_defense import AuditDefenseBoundaryRejected, PostgreSQLGovernedAuditGuidelineAdapter
from jmoraIs.clinical import HumanReviewStatus
from jmoraIs.guideline_engine import (
    GovernedGuidelineSourceService, GuidelineRecommendationEngine, InMemoryGovernedTerminologyConceptQueryAdapter,
    InMemoryGuidelineSourceRepository, InMemoryRecommendationAuditAdapter, InMemoryRecommendationRepository,
)
from tests.test_clinical_appraisal_domain import TODAY
from tests.test_clinical_appraisal_persistence import workflow
from tests.test_guideline_engine import EvidenceQuery, Lifecycle, NOW, evidence, guideline, ready_input, setup


class ReasoningQuery:
    def __init__(self, value): self.value = value
    def get(self, identifier): return self.value if identifier == self.value.input_id else None


def environment(*, guidelines=None, input_value=None):
    reasoning = input_value or ready_input()
    _, appraisal_source, appraisal_repository, appraisal_service = workflow()
    appraisal = appraisal_service.assess_and_persist((appraisal_source,), as_of=TODAY)[0][0]
    sources = InMemoryGuidelineSourceRepository(); source_service = GovernedGuidelineSourceService(sources, clock=lambda: NOW)
    source_values = tuple(guidelines or (guideline(),))
    for item in source_values:
        source_service.persist(item, appraisal_reference=appraisal.appraisal_id, governance_status="ACTIVE")
    engine, repository, _ = setup(guidelines=source_values)
    value = engine.create_recommendation_set(reasoning)
    adapter = PostgreSQLGovernedAuditGuidelineAdapter(
        repository, sources, ReasoningQuery(reasoning), appraisal_service,
        InMemoryGovernedTerminologyConceptQueryAdapter(()), clock=lambda: NOW,
    )
    return adapter, value, reasoning, sources, source_service, appraisal


def test_projection_preserves_canonical_guideline_semantics_and_traceability():
    adapter, value, *_ = environment(); reread = adapter.latest(value.subject_reference)
    assert reread is value
    recommendation = reread.recommendations[0]
    assert recommendation.guideline_id == "guideline-1" and recommendation.guideline_version == "2026.1"
    assert recommendation.explanation.organization == "Society"
    assert recommendation.explanation.strength.name == "CONDITIONAL_FOR"
    assert recommendation.explanation.applicability.matched_contexts == ("ADULT",)
    assert recommendation.review_status is HumanReviewStatus.PENDING_REVIEW
    assert recommendation.provenance_references and recommendation.policy_version == "MIP-04-v1"


def test_missing_forged_reasoning_and_provenance_fail_closed():
    adapter, value, reasoning, sources, _, appraisal = environment()
    adapter._recommendations = type("Missing", (), {"latest":lambda self, subject:None})()
    with pytest.raises(AuditDefenseBoundaryRejected): adapter.latest(value.subject_reference)
    forged = replace(value, set_id="forged")
    adapter._recommendations = type("Forged", (), {"latest":lambda self, subject:forged,
        "history":lambda self, subject:(forged,)})()
    with pytest.raises(AuditDefenseBoundaryRejected): adapter.latest(value.subject_reference)
    adapter._recommendations = type("Valid", (), {"latest":lambda self, subject:value,
        "history":lambda self, subject:(value,)})()
    adapter._reasoning_inputs = ReasoningQuery(replace(reasoning, input_id="other-input"))
    with pytest.raises(AuditDefenseBoundaryRejected): adapter.latest(value.subject_reference)
    missing_provenance = replace(value, provenance_references=())
    adapter._recommendations = type("NoProvenance", (), {"latest":lambda self, subject:missing_provenance})()
    with pytest.raises(AuditDefenseBoundaryRejected): adapter.latest(value.subject_reference)


@pytest.mark.parametrize("changes", (
    {"expiration_date": date(2025, 1, 1)}, {"withdrawn_at": date(2026, 1, 1)}, {"superseded_by":"new-guideline"},
))
def test_expired_withdrawn_and_superseded_current_sources_fail_closed(changes):
    adapter, value, _, _, source_service, appraisal = environment()
    source_service.persist(replace(guideline(), **changes), appraisal_reference=appraisal.appraisal_id,
                           governance_status="ACTIVE")
    with pytest.raises(AuditDefenseBoundaryRejected): adapter.latest(value.subject_reference)


def test_invalid_appraisal_terminology_policy_and_rejected_review_fail_closed():
    adapter, value, _, sources, _, appraisal = environment()
    adapter._appraisals = type("MissingAppraisal", (), {"get":lambda self, identifier:None})()
    with pytest.raises(AuditDefenseBoundaryRejected): adapter.latest(value.subject_reference)
    adapter, value, *_ = environment()
    bad = replace(value.recommendations[0], terminology_versions=("wrong",))
    altered = replace(value, recommendations=(bad,))
    adapter._recommendations = type("BadTerminology", (), {"latest":lambda self, subject:altered,
        "history":lambda self, subject:(altered,)})()
    with pytest.raises(AuditDefenseBoundaryRejected): adapter.latest(value.subject_reference)
    adapter, value, *_ = environment()
    bad = replace(value.recommendations[0], policy_version="wrong")
    altered = replace(value, recommendations=(bad,))
    adapter._recommendations = type("BadPolicy", (), {"latest":lambda self, subject:altered,
        "history":lambda self, subject:(altered,)})()
    with pytest.raises(AuditDefenseBoundaryRejected): adapter.latest(value.subject_reference)
    adapter, value, *_ = environment()
    rejected = replace(value, review_status=HumanReviewStatus.REJECTED_BY_REVIEWER)
    adapter._recommendations = type("Rejected", (), {"latest":lambda self, subject:rejected,
        "history":lambda self, subject:(rejected,)})()
    with pytest.raises(AuditDefenseBoundaryRejected): adapter.latest(value.subject_reference)


def test_critical_conflict_is_preserved_not_downgraded():
    second = guideline("guideline-2", "guideline-rec-2", organization="Other", intent=
        __import__("jmoraIs.guideline_engine", fromlist=["RecommendationIntent"]).RecommendationIntent.AVOID)
    reasoning = ready_input(); reasoning = replace(reasoning, applicable_guidelines=reasoning.applicable_guidelines+
        (replace(reasoning.applicable_guidelines[0], reference_id="guideline-2", organization="Other"),))
    adapter, value, *_ = environment(guidelines=(guideline(), second), input_value=reasoning)
    reread = adapter.latest(value.subject_reference)
    assert any(conflict.severity.value == "CRITICAL_CONFLICT"
               for item in reread.recommendations for conflict in item.explanation.conflicts)
