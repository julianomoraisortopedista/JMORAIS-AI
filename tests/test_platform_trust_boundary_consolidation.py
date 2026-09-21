from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone

import pytest

import jmoraIs.clinical as public_clinical
from jmoraIs.appraisal import ClinicalAppraisalService, GovernedEvidenceService, InMemoryGovernedEvidenceRepository
from jmoraIs.clinical import (
    AuthorizedRecommendationReviewService,
    DeprecatedClinicalPathError,
    GovernedClinicalIntelligenceService,
    GovernedEvidenceEligibilityGate,
    GovernedEvidenceRejected,
    GovernedEvidenceReevaluationService,
    GovernedRecommendationCandidate,
    HumanReviewStatus,
    InMemoryGovernedDecisionAuditRepository,
    InMemoryGovernedEvidenceLifecycleRepository,
    InMemoryReviewerAuthorizationAdapter,
    ReviewAuthorizationPolicy,
    ReviewerIdentity,
    ReviewerRole,
)
from jmoraIs.clinical.application import ClinicalIntelligenceService as DeprecatedST12Service
from jmoraIs.clinical.governed import RecommendationReviewService, _hash
from jmoraIs.clinical.review_governance import (
    GovernedEvidenceLifecycleEvent,
    GovernedEvidenceLifecycleStatus,
)
from jmoraIs.clinical_engine import ClinicalDecisionEngine
from jmoraIs.evidence_ledger import LedgerEventType
from jmoraIs.scientific_domain import EligibleEvidenceResult, SearchRun
from tests.test_clinical_appraisal_domain import guideline, request
from tests.test_clinical_intelligence_foundation import issue_direction, package_port
from tests.test_evidence_package_boundary import NOW


def governed_setup(*, governance=None, assessed_on=date(2026, 1, 1)):
    packages = package_port()
    package = issue_direction(packages, "supporting", "st18")
    source = request(identifier="rec-st18", package_id=package.package_id,
                     governance=governance or guideline())
    appraisal = ClinicalAppraisalService(packages).assess((source,), as_of=assessed_on)[0][0]
    governed = GovernedEvidenceService(
        packages, InMemoryGovernedEvidenceRepository(), clock=lambda: NOW,
    )
    evidence = governed.issue(appraisal, source)
    return packages, package, governed, evidence


def clinical_with_lifecycle(packages, governed, lifecycle, *, clock=lambda: NOW):
    audit = InMemoryGovernedDecisionAuditRepository()
    reevaluation = GovernedEvidenceReevaluationService(
        packages, lifecycle, clock=clock,
    )
    gate = GovernedEvidenceEligibilityGate(reevaluation)
    service = GovernedClinicalIntelligenceService(governed, audit, gate, clock=clock)
    return service, audit, reevaluation


def candidate(identifier):
    return GovernedRecommendationCandidate(
        "candidate", "Governed recommendation", (identifier,), ("ADULT",),
    )


def lifecycle_event(evidence, status, previous_hash=None):
    event_id = f"event-{status.value.lower()}"
    payload = {
        "event_id": event_id, "governed_evidence_id": evidence.governed_evidence_id,
        "status": status.value, "triggers": [], "occurred_at": NOW.isoformat(),
        "actor_id": "test-policy", "policy_version": evidence.policy_version,
        "previous_event_hash": previous_hash,
    }
    return GovernedEvidenceLifecycleEvent(
        event_id, evidence.governed_evidence_id, status, (), NOW, "test-policy",
        evidence.policy_version, previous_hash, _hash(payload),
    )


def test_raw_package_internal_result_and_dict_cannot_enter_trusted_clinical_service():
    packages, package, governed, _ = governed_setup()
    lifecycle = InMemoryGovernedEvidenceLifecycleRepository()
    service, _, _ = clinical_with_lifecycle(packages, governed, lifecycle)
    for raw in (
        package,
        EligibleEvidenceResult(search_run=SearchRun(query="internal")),
        {"verification_status": "VERIFIED"},
    ):
        with pytest.raises(ValueError, match="opaque strings"):
            candidate(raw)


def test_both_legacy_clinical_services_are_fail_closed():
    packages = package_port()
    with pytest.raises(DeprecatedClinicalPathError):
        ClinicalDecisionEngine(packages)
    with pytest.raises(DeprecatedClinicalPathError):
        DeprecatedST12Service(packages, object())


def test_unauthenticated_review_service_is_fail_closed_and_not_public():
    with pytest.raises(DeprecatedClinicalPathError, match="authorization"):
        RecommendationReviewService(object())
    assert not hasattr(public_clinical, "RecommendationReviewService")


def test_approval_always_requires_authorized_identity():
    packages, _, governed, evidence = governed_setup()
    service, audit, _ = clinical_with_lifecycle(
        packages, governed, InMemoryGovernedEvidenceLifecycleRepository(),
    )
    recommendation = service.evaluate(case_id="case", candidates=(
        candidate(evidence.governed_evidence_id),
    ))[0]
    authorization = InMemoryReviewerAuthorizationAdapter(())
    review = AuthorizedRecommendationReviewService(
        authorization, audit, ReviewAuthorizationPolicy(), clock=lambda: NOW,
    )
    with pytest.raises(Exception, match="authorized"):
        review.transition(case_id="case", recommendation=recommendation,
            target=HumanReviewStatus.APPROVED_BY_REVIEWER, reviewer_id="unknown",
            justification="Attempted approval.")


def test_active_state_is_rechecked_and_later_expiration_blocks():
    clock = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    governance = guideline(expires=date(2026, 1, 2))
    packages, _, governed, evidence = governed_setup(governance=governance)
    lifecycle = InMemoryGovernedEvidenceLifecycleRepository()
    service, _, _ = clinical_with_lifecycle(
        packages, governed, lifecycle, clock=lambda: clock[0],
    )
    assert service.evaluate(case_id="case-before", candidates=(
        candidate(evidence.governed_evidence_id),
    ))
    clock[0] = datetime(2026, 1, 3, tzinfo=timezone.utc)
    with pytest.raises(GovernedEvidenceRejected, match="REVIEW_REQUIRED"):
        service.evaluate(case_id="case-after", candidates=(
            candidate(evidence.governed_evidence_id),
        ))


@pytest.mark.parametrize("status", [
    GovernedEvidenceLifecycleStatus.REVIEW_REQUIRED,
    GovernedEvidenceLifecycleStatus.SUPERSEDED,
    GovernedEvidenceLifecycleStatus.INVALIDATED,
])
def test_non_active_lifecycle_states_block_new_decisions(status):
    packages, _, governed, evidence = governed_setup()
    lifecycle = InMemoryGovernedEvidenceLifecycleRepository()
    lifecycle.append(lifecycle_event(evidence, status))
    service, _, _ = clinical_with_lifecycle(packages, governed, lifecycle)
    with pytest.raises(GovernedEvidenceRejected, match=status.value):
        service.evaluate(case_id=f"case-{status.value}", candidates=(
            candidate(evidence.governed_evidence_id),
        ))


def test_package_revocation_propagates_without_cached_eligibility():
    packages, package, governed, evidence = governed_setup()
    lifecycle = InMemoryGovernedEvidenceLifecycleRepository()
    service, _, _ = clinical_with_lifecycle(packages, governed, lifecycle)
    assert service.evaluate(case_id="case-active", candidates=(
        candidate(evidence.governed_evidence_id),
    ))
    record = packages._catalog.get(package.package_id)
    relationship = package.claim_evidence_relationships[0]
    record.ledger.append_lifecycle_event(
        claim_id=relationship.claim_id, event_type=LedgerEventType.RETRACTION,
        target_support_id=relationship.support_id, reason="Retracted", occurred_at=NOW,
    )
    with pytest.raises(GovernedEvidenceRejected):
        service.evaluate(case_id="case-revoked", candidates=(
            candidate(evidence.governed_evidence_id),
        ))


def test_guideline_withdrawal_propagates_to_eligibility():
    clock = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    governance = guideline(withdrawn=date(2026, 1, 2), expires=date(2027, 1, 1))
    packages, _, governed, evidence = governed_setup(governance=governance)
    lifecycle = InMemoryGovernedEvidenceLifecycleRepository()
    service, _, _ = clinical_with_lifecycle(
        packages, governed, lifecycle, clock=lambda: clock[0],
    )
    assert service.evaluate(case_id="case-before", candidates=(
        candidate(evidence.governed_evidence_id),
    ))
    clock[0] = datetime(2026, 1, 2, tzinfo=timezone.utc)
    with pytest.raises(GovernedEvidenceRejected, match="REVIEW_REQUIRED"):
        service.evaluate(case_id="case-withdrawn", candidates=(
            candidate(evidence.governed_evidence_id),
        ))


def test_policy_version_change_requires_review_and_never_auto_approves():
    packages, _, governed, evidence = governed_setup()
    lifecycle = InMemoryGovernedEvidenceLifecycleRepository()
    reevaluation = GovernedEvidenceReevaluationService(
        packages, lifecycle, policy_version="new-policy", clock=lambda: NOW,
    )
    service = GovernedClinicalIntelligenceService(
        governed, InMemoryGovernedDecisionAuditRepository(),
        GovernedEvidenceEligibilityGate(reevaluation), clock=lambda: NOW,
    )
    with pytest.raises(GovernedEvidenceRejected, match="REVIEW_REQUIRED"):
        service.evaluate(case_id="case-policy", candidates=(
            candidate(evidence.governed_evidence_id),
        ))
    assert lifecycle.history(evidence.governed_evidence_id)[-1].status == (
        GovernedEvidenceLifecycleStatus.REVIEW_REQUIRED
    )


def test_public_contract_contains_only_governed_clinical_and_authorized_review():
    assert public_clinical.ClinicalIntelligenceService is GovernedClinicalIntelligenceService
    assert "FoundationClinicalIntelligenceService" not in public_clinical.__dict__
    assert "RecommendationReviewService" not in public_clinical.__dict__
    assert "EvidenceAppraisal" not in public_clinical.__dict__
