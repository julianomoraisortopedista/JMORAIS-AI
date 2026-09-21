from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import date

import pytest

from jmoraIs.appraisal import (
    ApplicabilityContext,
    AppraisalRequest,
    AssessmentRating,
    EvidenceLevel,
    GuidelineConflictResolver,
    GuidelineGovernance,
    GuidelineStatus,
    MethodologicalQuality,
    MethodologicalQualityAssessment,
    RecommendationStrength,
    RiskOfBias,
)
from jmoraIs.appraisal.domain import ConflictType


TODAY = date(2026, 1, 1)


def quality(*, risk=RiskOfBias.LOW, rating=AssessmentRating.ADEQUATE, limitations=()):
    return MethodologicalQualityAssessment(
        risk, rating, rating, rating, rating, rating, rating, rating, limitations,
    )


def guideline(
    identifier="guideline-1", organization="Society A", published=date(2025, 1, 1),
    revised=None, expires=date(2027, 1, 1), superseded=None, withdrawn=None,
):
    return GuidelineGovernance(
        identifier, organization, published, revised, expires, superseded, withdrawn,
        ("BR",), ("orthopedics",),
    )


def request(
    identifier="rec-1", topic="topic-1", strength=RecommendationStrength.STRONG_FOR,
    governance=None, level=EvidenceLevel.RANDOMIZED_CONTROLLED_TRIAL,
    assessment=None, contexts=(ApplicabilityContext.ADULT,), package_id="package-1",
):
    return AppraisalRequest(
        identifier, topic, f"Recommendation {identifier}", package_id, level,
        assessment or quality(), strength, governance or guideline(), contexts,
    )


def test_methodological_quality_exposes_all_dimensions_and_score():
    assessment = quality()
    assert assessment.risk_of_bias == RiskOfBias.LOW
    assert assessment.randomization == AssessmentRating.ADEQUATE
    assert assessment.allocation_concealment == AssessmentRating.ADEQUATE
    assert assessment.blinding == AssessmentRating.ADEQUATE
    assert assessment.attrition == AssessmentRating.ADEQUATE
    assert assessment.selective_reporting == AssessmentRating.ADEQUATE
    assert assessment.external_validity == AssessmentRating.ADEQUATE
    assert assessment.statistical_robustness == AssessmentRating.ADEQUATE
    assert assessment.score == 1.0
    assert assessment.quality == MethodologicalQuality.HIGH


def test_not_applicable_dimensions_do_not_penalize_observational_design():
    assessment = MethodologicalQualityAssessment(
        RiskOfBias.LOW, AssessmentRating.NOT_APPLICABLE, AssessmentRating.NOT_APPLICABLE,
        AssessmentRating.NOT_APPLICABLE, AssessmentRating.ADEQUATE, AssessmentRating.ADEQUATE,
        AssessmentRating.PROBABLY_ADEQUATE, AssessmentRating.ADEQUATE,
    )
    assert assessment.score == pytest.approx(0.95)
    assert assessment.quality == MethodologicalQuality.HIGH


@pytest.mark.parametrize("risk,rating,expected", [
    (RiskOfBias.LOW, AssessmentRating.ADEQUATE, MethodologicalQuality.HIGH),
    (RiskOfBias.SOME_CONCERNS, AssessmentRating.SOME_CONCERNS, MethodologicalQuality.LOW),
    (RiskOfBias.HIGH, AssessmentRating.INADEQUATE, MethodologicalQuality.VERY_LOW),
])
def test_methodological_quality_classification(risk, rating, expected):
    assert quality(risk=risk, rating=rating).quality == expected


def test_evidence_hierarchy_is_explicit_and_complete():
    ordered = sorted(EvidenceLevel, reverse=True)
    assert ordered == [
        EvidenceLevel.SYSTEMATIC_REVIEW, EvidenceLevel.META_ANALYSIS,
        EvidenceLevel.RANDOMIZED_CONTROLLED_TRIAL, EvidenceLevel.COHORT,
        EvidenceLevel.CASE_CONTROL, EvidenceLevel.CROSS_SECTIONAL,
        EvidenceLevel.CASE_SERIES, EvidenceLevel.CASE_REPORT, EvidenceLevel.EXPERT_OPINION,
    ]


def test_recommendation_strength_has_ordered_direction():
    assert RecommendationStrength.STRONG_FOR > RecommendationStrength.CONDITIONAL_FOR
    assert RecommendationStrength.CONDITIONAL_FOR > RecommendationStrength.NEUTRAL
    assert RecommendationStrength.NEUTRAL > RecommendationStrength.CONDITIONAL_AGAINST
    assert RecommendationStrength.CONDITIONAL_AGAINST > RecommendationStrength.STRONG_AGAINST


def test_guideline_governance_validates_dates_and_scope():
    with pytest.raises(ValueError, match="revision"):
        guideline(revised=date(2024, 1, 1))
    with pytest.raises(ValueError, match="regional"):
        GuidelineGovernance("id", "org", TODAY, None, None, None, None, (), ("specialty",))


def test_guideline_expiration_is_automatic():
    item = guideline(expires=date(2025, 12, 31))
    assert item.status(TODAY) == GuidelineStatus.EXPIRED


def test_superseded_guideline_is_detected():
    assert guideline(superseded="guideline-2").status(TODAY) == GuidelineStatus.SUPERSEDED


def test_withdrawn_guideline_has_highest_status_precedence():
    item = guideline(superseded="guideline-2", withdrawn=date(2025, 6, 1))
    assert item.status(TODAY) == GuidelineStatus.WITHDRAWN
    assert item.status(date(2025, 1, 1)) == GuidelineStatus.SUPERSEDED


def test_applicability_requires_unique_explicit_contexts():
    with pytest.raises(ValueError, match="unique"):
        request(contexts=(ApplicabilityContext.ADULT, ApplicabilityContext.ADULT))
    item = request(contexts=tuple(ApplicabilityContext))
    assert set(item.applicability) == set(ApplicabilityContext)


def test_domain_entities_are_immutable():
    item = request()
    with pytest.raises(FrozenInstanceError):
        item.recommendation = "changed"


def test_conflicting_recommendations_organizations_and_dates_are_detected():
    first = request("for", strength=RecommendationStrength.STRONG_FOR)
    second = request(
        "against", strength=RecommendationStrength.CONDITIONAL_AGAINST,
        governance=guideline("guideline-2", "Society B", date(2024, 1, 1)),
        package_id="package-2",
    )
    result = GuidelineConflictResolver().resolve((first, second), TODAY)
    assert {item.conflict_type for item in result.conflicts} == {
        ConflictType.RECOMMENDATION, ConflictType.ORGANIZATION, ConflictType.PUBLICATION_DATE,
    }
    assert all(item.recommendation_ids == ("against", "for") for item in result.conflicts)


def test_resolution_order_prefers_active_higher_evidence():
    expired = request("expired", governance=guideline(expires=date(2025, 1, 1)),
                      level=EvidenceLevel.SYSTEMATIC_REVIEW)
    active = request("active", governance=guideline("active"),
                     level=EvidenceLevel.COHORT, package_id="package-2")
    result = GuidelineConflictResolver().resolve((expired, active), TODAY)
    assert result.resolution_order == ("active", "expired")


def test_same_direction_does_not_create_false_conflict():
    first = request("strong")
    second = request("conditional", strength=RecommendationStrength.CONDITIONAL_FOR,
                     package_id="package-2")
    assert GuidelineConflictResolver().resolve((first, second), TODAY).conflicts == ()
