from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from jmoraIs.appraisal import (
    ApplicabilityContext,
    ClinicalAppraisalService,
    GovernedEvidenceError,
    GovernedEvidenceService,
    InMemoryGovernedEvidenceRepository,
    RecommendationStrength,
)
from jmoraIs.clinical import (
    CriticalConflictRequiresReview,
    GovernedClinicalIntelligenceService,
    GovernedEvidenceEligibilityGate,
    GovernedEvidenceReevaluationService,
    GovernedEvidenceRejected,
    GovernedRecommendationCandidate,
    HumanReviewStatus,
    InMemoryGovernedDecisionAuditRepository,
    InMemoryGovernedEvidenceLifecycleRepository,
    AuthorizedRecommendationReviewService,
    InMemoryReviewerAuthorizationAdapter,
    ReviewAuthorizationPolicy,
    ReviewerIdentity,
    ReviewerRole,
    ReviewTransitionRejected,
)
from jmoraIs.evidence_ledger import LedgerEventType
from tests.test_clinical_appraisal_domain import TODAY, guideline, request
from tests.test_clinical_intelligence_foundation import issue_direction, package_port
from tests.test_evidence_package_boundary import NOW


def governed_fixture(*, suffix="valid", governance=None, contexts=(ApplicabilityContext.ADULT,), direction="supporting"):
    packages = package_port()
    package = issue_direction(packages, direction, suffix)
    appraisal_request = request(
        identifier=f"rec-{suffix}", package_id=package.package_id,
        governance=governance, contexts=contexts,
    )
    appraised = ClinicalAppraisalService(packages).assess((appraisal_request,), as_of=TODAY)[0][0]
    repository = InMemoryGovernedEvidenceRepository()
    governed = GovernedEvidenceService(packages, repository, clock=lambda: NOW)
    evidence = governed.issue(appraised, appraisal_request)
    return packages, package, appraisal_request, appraised, repository, governed, evidence


def candidate(evidence_id, *, identifier="candidate", applicability=("ADULT",)):
    return GovernedRecommendationCandidate(identifier, f"Recommendation {identifier}",
                                            (evidence_id,), applicability)


def clinical(governed):
    audit = InMemoryGovernedDecisionAuditRepository()
    lifecycle = GovernedEvidenceReevaluationService(
        governed._packages, InMemoryGovernedEvidenceLifecycleRepository(), clock=lambda: NOW,
    )
    gate = GovernedEvidenceEligibilityGate(lifecycle)
    return GovernedClinicalIntelligenceService(governed, audit, gate, clock=lambda: NOW), audit


def test_valid_governed_evidence_is_accepted_and_ranked():
    *_, governed, evidence = governed_fixture()
    service, _ = clinical(governed)
    result = service.evaluate(case_id="case-1", candidates=(candidate(evidence.governed_evidence_id),))
    assert result[0].rank == 1
    assert result[0].review_status == HumanReviewStatus.PENDING_REVIEW
    assert not result[0].externally_actionable


def test_raw_evidence_package_and_arbitrary_dictionary_are_rejected():
    _, package, *_, governed, evidence = governed_fixture()
    service, _ = clinical(governed)
    with pytest.raises(ValueError, match="opaque strings"):
        candidate(package)
    with pytest.raises(ValueError, match="opaque strings"):
        candidate({"appraisal": "VALID"})


def test_missing_appraisal_is_rejected():
    *_, governed, _ = governed_fixture()
    service, _ = clinical(governed)
    with pytest.raises(GovernedEvidenceRejected):
        service.evaluate(case_id="case", candidates=(candidate("missing-appraisal"),))


def test_invalidated_underlying_evidence_package_is_rejected_at_use_time():
    packages, package, *_, governed, evidence = governed_fixture(suffix="invalidated-package")
    catalog_record = packages._catalog.get(package.package_id)
    relationship = package.claim_evidence_relationships[0]
    catalog_record.ledger.append_lifecycle_event(
        claim_id=relationship.claim_id, event_type=LedgerEventType.INVALIDATION,
        target_support_id=relationship.support_id, reason="Evidence invalidated", occurred_at=NOW,
    )
    service, _ = clinical(governed)
    with pytest.raises(GovernedEvidenceRejected):
        service.evaluate(case_id="case", candidates=(candidate(evidence.governed_evidence_id),))


@pytest.mark.parametrize("governance,status", [
    (guideline(expires=date(2025, 1, 1)), "EXPIRED_GUIDELINE"),
    (guideline(withdrawn=date(2025, 1, 1)), "WITHDRAWN_RECOMMENDATION"),
    (guideline(superseded="authoritative-replacement"), "SUPERSEDED_RECOMMENDATION"),
])
def test_invalid_guideline_lifecycle_is_rejected(governance, status):
    *_, governed, evidence = governed_fixture(suffix=status, governance=governance)
    service, _ = clinical(governed)
    with pytest.raises(GovernedEvidenceRejected, match=status):
        service.evaluate(case_id="case", candidates=(candidate(evidence.governed_evidence_id),))


def test_applicability_mismatch_is_rejected():
    *_, governed, evidence = governed_fixture(contexts=(ApplicabilityContext.PEDIATRIC,))
    service, _ = clinical(governed)
    with pytest.raises(GovernedEvidenceRejected, match="applicability"):
        service.evaluate(case_id="case", candidates=(candidate(evidence.governed_evidence_id),))


def test_incomplete_governance_and_missing_provenance_are_rejected():
    *_, repository, governed, evidence = governed_fixture()
    repository._items[evidence.governed_evidence_id] = replace(evidence, provenance_references=())
    service, _ = clinical(governed)
    with pytest.raises(GovernedEvidenceRejected):
        service.evaluate(case_id="case", candidates=(candidate(evidence.governed_evidence_id),))


def test_governed_boundary_rejects_arbitrary_appraisal_dictionary():
    packages = package_port()
    service = GovernedEvidenceService(packages, InMemoryGovernedEvidenceRepository())
    with pytest.raises(GovernedEvidenceError, match="typed appraisal"):
        service.issue({"eligible": True}, {"evidence_package_id": "fake"})


def test_conflicting_guidance_is_preserved_and_requires_review():
    packages = package_port()
    package_for = issue_direction(packages, "supporting", "conflict-for")
    package_against = issue_direction(packages, "opposing", "conflict-against")
    requests = (
        request("for", package_id=package_for.package_id),
        request("against", package_id=package_against.package_id,
                strength=RecommendationStrength.STRONG_AGAINST,
                governance=guideline("other", "Society B", date(2024, 1, 1))),
    )
    appraised, _ = ClinicalAppraisalService(packages).assess(requests, as_of=TODAY)
    repo = InMemoryGovernedEvidenceRepository()
    governed = GovernedEvidenceService(packages, repo, clock=lambda: NOW)
    evidence = tuple(governed.issue(result, source) for result, source in zip(appraised, requests))
    assert "CONFLICTING_RECOMMENDATIONS" in evidence[0].conflict_status
    service, audit = clinical(governed)
    with pytest.raises(CriticalConflictRequiresReview, match="human"):
        service.evaluate(case_id="case", candidates=(candidate(evidence[0].governed_evidence_id),))
    blocked = audit.history("case")[0]
    assert blocked.event_type == "CRITICAL_CONFLICT_BLOCKED"
    assert "CONFLICTING_RECOMMENDATIONS" in blocked.conflict_decisions


def test_provenance_and_appraisal_explainability_are_retained():
    *_, governed, evidence = governed_fixture()
    service, _ = clinical(governed)
    recommendation = service.evaluate(case_id="case", candidates=(candidate(evidence.governed_evidence_id),))[0]
    assert recommendation.provenance_references == evidence.provenance_references
    assert recommendation.ledger_references == evidence.ledger_references
    explanation = recommendation.explanation
    assert explanation.appraisal_quality == ("HIGH",)
    assert explanation.evidence_hierarchy == ("RANDOMIZED_CONTROLLED_TRIAL",)
    assert explanation.guideline_authorities == ("Society A",)
    assert explanation.recommendation_strengths == ("STRONG_FOR",)
    assert explanation.applicability == ("ADULT",)
    assert explanation.human_review_status == HumanReviewStatus.PENDING_REVIEW


def test_support_opposition_neutral_and_inconclusive_are_not_collapsed():
    packages = package_port()
    repo = InMemoryGovernedEvidenceRepository()
    governed = GovernedEvidenceService(packages, repo, clock=lambda: NOW)
    evidence_ids = []
    for direction in ("supporting", "opposing", "neutral", "inconclusive"):
        package = issue_direction(packages, direction, direction)
        req = request(direction, package_id=package.package_id)
        appraised = ClinicalAppraisalService(packages).assess((req,), as_of=TODAY)[0][0]
        evidence_ids.append(governed.issue(appraised, req).governed_evidence_id)
    service, _ = clinical(governed)
    result = service.evaluate(case_id="case", candidates=(
        GovernedRecommendationCandidate("all", "All directions", tuple(evidence_ids), ("ADULT",)),
    ))[0]
    assert result.explanation.supporting_weight > 0
    assert result.explanation.opposing_weight > 0
    assert result.explanation.neutral_weight > 0
    assert result.explanation.inconclusive_weight > 0


def test_deterministic_ranking_uses_governed_appraisal_quality():
    packages = package_port()
    repo = InMemoryGovernedEvidenceRepository()
    governed = GovernedEvidenceService(packages, repo, clock=lambda: NOW)
    ids = []
    for suffix in ("a", "b"):
        package = issue_direction(packages, "supporting", f"rank-{suffix}")
        req = request(f"rank-{suffix}", package_id=package.package_id)
        appraised = ClinicalAppraisalService(packages).assess((req,), as_of=TODAY)[0][0]
        ids.append(governed.issue(appraised, req).governed_evidence_id)
    service, _ = clinical(governed)
    result = service.evaluate(case_id="case", candidates=(candidate(ids[1], identifier="b"), candidate(ids[0], identifier="a")))
    assert [item.candidate_id for item in result] == ["a", "b"]


def test_audit_trail_records_governed_inputs_weighting_conflicts_and_confidence():
    *_, governed, evidence = governed_fixture()
    service, audit = clinical(governed)
    recommendation = service.evaluate(case_id="case-audit", candidates=(candidate(evidence.governed_evidence_id),))[0]
    event = audit.history("case-audit")[0]
    assert event.governed_evidence_ids == (evidence.governed_evidence_id,)
    assert event.recommendation_ids == (recommendation.recommendation_id,)
    assert event.weighting_decisions
    assert event.confidence_inputs
    assert event.review_to == HumanReviewStatus.PENDING_REVIEW.value


def test_reviewer_approval_and_rejection_lifecycle_are_append_only():
    *_, governed, evidence = governed_fixture()
    service, audit = clinical(governed)
    pending = service.evaluate(case_id="case-review", candidates=(candidate(evidence.governed_evidence_id),))[0]
    authorization = InMemoryReviewerAuthorizationAdapter((
        ReviewerIdentity("reviewer-1", ReviewerRole.REVIEWER),
        ReviewerIdentity("reviewer-2", ReviewerRole.REVIEWER),
    ))
    review = AuthorizedRecommendationReviewService(
        authorization, audit, ReviewAuthorizationPolicy(), clock=lambda: NOW,
    )
    approved = review.transition(case_id="case-review", recommendation=pending,
        target=HumanReviewStatus.APPROVED_BY_REVIEWER, reviewer_id="reviewer-1",
        justification="Evidence reviewed.", generated_by="system")
    assert approved.externally_actionable
    assert approved.explanation.human_review_status == HumanReviewStatus.APPROVED_BY_REVIEWER
    assert audit.history("case-review")[-1].reviewer_id == "reviewer-1"

    pending_two = service.evaluate(case_id="case-reject", candidates=(candidate(evidence.governed_evidence_id),))[0]
    rejected = review.transition(case_id="case-reject", recommendation=pending_two,
        target=HumanReviewStatus.REJECTED_BY_REVIEWER, reviewer_id="reviewer-2",
        justification="Evidence rejected.", generated_by="system")
    assert not rejected.externally_actionable
    with pytest.raises(ReviewTransitionRejected):
        review.transition(case_id="case-reject", recommendation=rejected,
            target=HumanReviewStatus.APPROVED_BY_REVIEWER, reviewer_id="reviewer-2",
            justification="Invalid reversal.", generated_by="system")
