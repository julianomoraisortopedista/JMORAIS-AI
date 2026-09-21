from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from jmoraIs.appraisal import (
    ClinicalAppraisalService, GovernedEvidenceService,
    GovernedEvidencePersistenceBase, SQLAlchemyGovernedEvidenceRepository,
)
from jmoraIs.clinical import (
    AuthorizedRecommendationReviewService, ConflictAdjudicationService,
    ConflictAdjudicationState, GovernedClinicalIntelligenceService,
    GovernedEvidenceLifecycleStatus, GovernedEvidenceReevaluationService,
    GovernedRecommendationCandidate, HumanReviewStatus,
    GovernedEvidenceEligibilityGate,
    InMemoryConflictAdjudicationRepository, InMemoryGovernedEvidenceLifecycleRepository,
    InMemoryReviewerAuthorizationAdapter, ReevaluationTrigger, ReviewAuthorizationPolicy,
    ReviewerIdentity, ReviewerRole, ReviewTransitionRejected,
)
from jmoraIs.clinical.governance_persistence import (
    ClinicalAuditEventRow, ClinicalGovernancePersistenceBase,
    ClinicalGovernancePersistenceError, SQLAlchemyConflictAdjudicationRepository,
    SQLAlchemyGovernedDecisionAuditRepository, SQLAlchemyGovernedEvidenceLifecycleRepository,
)
from jmoraIs.evidence_ledger import LedgerEventType
from tests.test_clinical_appraisal_domain import TODAY, guideline, request
from tests.test_clinical_intelligence_foundation import issue_direction, package_port
from tests.test_evidence_package_boundary import NOW


def database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'governance.db'}", future=True)
    GovernedEvidencePersistenceBase.metadata.create_all(engine)
    ClinicalGovernancePersistenceBase.metadata.create_all(engine)
    return engine


def persistent_governed(tmp_path, *, suffix="persistent", governance=None):
    packages = package_port()
    package = issue_direction(packages, "supporting", suffix)
    source = request(identifier=f"rec-{suffix}", package_id=package.package_id, governance=governance)
    appraisal = ClinicalAppraisalService(packages).assess((source,), as_of=TODAY)[0][0]
    engine = database(tmp_path)
    repository = SQLAlchemyGovernedEvidenceRepository(engine)
    service = GovernedEvidenceService(packages, repository, clock=lambda: NOW)
    evidence = service.issue(appraisal, source)
    return engine, packages, package, source, appraisal, service, evidence


def recommendation_with_audit(tmp_path, *, case_id="case-review"):
    engine, packages, package, source, appraisal, governed, evidence = persistent_governed(tmp_path)
    audit = SQLAlchemyGovernedDecisionAuditRepository(engine)
    lifecycle = GovernedEvidenceReevaluationService(
        packages, SQLAlchemyGovernedEvidenceLifecycleRepository(engine), clock=lambda: NOW,
    )
    service = GovernedClinicalIntelligenceService(
        governed, audit, GovernedEvidenceEligibilityGate(lifecycle), clock=lambda: NOW,
    )
    recommendation = service.evaluate(case_id=case_id, candidates=(
        GovernedRecommendationCandidate("candidate", "Governed recommendation",
            (evidence.governed_evidence_id,), ("ADULT",)),
    ))[0]
    return engine, packages, package, governed, evidence, audit, recommendation


def authorization():
    return InMemoryReviewerAuthorizationAdapter((
        ReviewerIdentity("reviewer", ReviewerRole.REVIEWER),
        ReviewerIdentity("senior", ReviewerRole.SENIOR_REVIEWER),
        ReviewerIdentity("admin", ReviewerRole.ADMINISTRATOR),
        ReviewerIdentity("inactive", ReviewerRole.SENIOR_REVIEWER, active=False),
    ))


def test_governed_evidence_persists_and_replays_after_restart(tmp_path):
    engine, packages, _, _, _, _, evidence = persistent_governed(tmp_path)
    restarted_repository = SQLAlchemyGovernedEvidenceRepository(engine)
    restarted = GovernedEvidenceService(packages, restarted_repository, clock=lambda: NOW)
    assert restarted.get(evidence.governed_evidence_id) == evidence
    assert restarted_repository.find_by_package_id(evidence.evidence_package_id) == (evidence,)


def test_governed_evidence_history_keeps_immutable_versions(tmp_path):
    engine, _, _, source, appraisal, service, first = persistent_governed(tmp_path)
    second = service.issue(appraisal, source)
    history = SQLAlchemyGovernedEvidenceRepository(engine).version_history(first.evidence_package_id)
    assert history == (first, second)
    assert first.governed_evidence_id != second.governed_evidence_id
    with pytest.raises(FrozenInstanceError):
        first.policy_version = "tampered"


def test_governed_repository_has_no_destructive_api(tmp_path):
    repository = SQLAlchemyGovernedEvidenceRepository(database(tmp_path))
    assert not hasattr(repository, "update")
    assert not hasattr(repository, "delete")


def test_persistent_audit_replays_hash_chain_after_restart(tmp_path):
    engine, _, _, _, evidence, audit, recommendation = recommendation_with_audit(tmp_path)
    restarted = SQLAlchemyGovernedDecisionAuditRepository(engine)
    history = restarted.history("case-review")
    assert history[0].governed_evidence_ids == (evidence.governed_evidence_id,)
    assert history[0].recommendation_ids == (recommendation.recommendation_id,)
    assert history[0].event_hash
    assert history[0].policy_version == "ST-14.1"


def test_persistent_audit_rejects_update_and_delete(tmp_path):
    engine, *_ = recommendation_with_audit(tmp_path)
    with Session(engine) as session:
        row = session.scalar(select(ClinicalAuditEventRow))
        row.event_hash = "tampered"
        with pytest.raises(ClinicalGovernancePersistenceError, match="UPDATE"):
            session.flush()


def test_authorized_reviewer_can_approve_with_attribution(tmp_path):
    _, _, _, _, _, audit, recommendation = recommendation_with_audit(tmp_path)
    service = AuthorizedRecommendationReviewService(
        authorization(), audit, ReviewAuthorizationPolicy(), clock=lambda: NOW)
    approved = service.transition(case_id="case-review", recommendation=recommendation,
        target=HumanReviewStatus.APPROVED_BY_REVIEWER, reviewer_id="reviewer",
        justification="Evidence and applicability reviewed.", generated_by="system")
    assert approved.externally_actionable
    event = audit.history("case-review")[-1]
    assert event.reviewer_id == "reviewer"
    assert event.actor_role == ReviewerRole.REVIEWER.value
    assert event.justification == "Evidence and applicability reviewed."
    assert event.policy_version == "ST-15.1"


def test_unauthorized_inactive_and_self_approval_are_rejected(tmp_path):
    _, _, _, _, _, audit, recommendation = recommendation_with_audit(tmp_path)
    service = AuthorizedRecommendationReviewService(authorization(), audit, ReviewAuthorizationPolicy())
    for reviewer_id in ("unknown", "inactive"):
        with pytest.raises(ReviewTransitionRejected, match="authorized"):
            service.transition(case_id="case-review", recommendation=recommendation,
                target=HumanReviewStatus.APPROVED_BY_REVIEWER, reviewer_id=reviewer_id,
                justification="Reviewed.")
    with pytest.raises(ReviewTransitionRejected, match="self-approval"):
        service.transition(case_id="case-review", recommendation=recommendation,
            target=HumanReviewStatus.APPROVED_BY_REVIEWER, reviewer_id="reviewer",
            justification="Reviewed.", generated_by="reviewer")


def test_critical_conflict_requires_senior_reviewer(tmp_path):
    _, _, _, _, _, audit, recommendation = recommendation_with_audit(tmp_path)
    conflicted = replace(recommendation, explanation=replace(
        recommendation.explanation, conflicts=("CONFLICTING_RECOMMENDATIONS",)))
    service = AuthorizedRecommendationReviewService(authorization(), audit, ReviewAuthorizationPolicy())
    with pytest.raises(ReviewTransitionRejected, match="senior"):
        service.transition(case_id="case-review", recommendation=conflicted,
            target=HumanReviewStatus.APPROVED_BY_REVIEWER, reviewer_id="reviewer",
            justification="Reviewed.")
    approved = service.transition(case_id="case-review", recommendation=conflicted,
        target=HumanReviewStatus.APPROVED_BY_REVIEWER, reviewer_id="senior",
        justification="Conflict adjudicated.")
    assert approved.externally_actionable


def test_rejected_or_clarification_recommendation_cannot_become_actionable(tmp_path):
    _, _, _, _, _, audit, recommendation = recommendation_with_audit(tmp_path)
    service = AuthorizedRecommendationReviewService(authorization(), audit, ReviewAuthorizationPolicy())
    rejected = service.transition(case_id="case-review", recommendation=recommendation,
        target=HumanReviewStatus.REJECTED_BY_REVIEWER, reviewer_id="reviewer",
        justification="Insufficient applicability.")
    assert not rejected.externally_actionable
    with pytest.raises(ReviewTransitionRejected, match="invalid"):
        service.transition(case_id="case-review", recommendation=rejected,
            target=HumanReviewStatus.APPROVED_BY_REVIEWER, reviewer_id="senior",
            justification="Attempted reversal.")


def test_conflict_adjudication_is_persistent_append_only_and_replayable(tmp_path):
    engine = database(tmp_path)
    repository = SQLAlchemyConflictAdjudicationRepository(engine)
    service = ConflictAdjudicationService(repository, authorization(), clock=lambda: NOW)
    opened = service.transition(conflict_id="conflict-1", case_id="case-1",
        target=ConflictAdjudicationState.OPEN,
        directions=("SUPPORTING", "OPPOSING", "NEUTRAL", "INCONCLUSIVE"),
        reviewer_id="reviewer", justification="Conflict registered.")
    reviewing = service.transition(conflict_id="conflict-1", case_id="case-1",
        target=ConflictAdjudicationState.UNDER_REVIEW, directions=opened.directions,
        reviewer_id="reviewer", justification="Review started.")
    resolved = service.transition(conflict_id="conflict-1", case_id="case-1",
        target=ConflictAdjudicationState.RESOLVED, directions=opened.directions,
        reviewer_id="senior", justification="Evidence adjudicated.")
    replayed = SQLAlchemyConflictAdjudicationRepository(engine).history("conflict-1")
    assert replayed == (opened, reviewing, resolved)
    assert replayed[1].previous_event_hash == replayed[0].event_hash
    assert replayed[0].directions == ("SUPPORTING", "OPPOSING", "NEUTRAL", "INCONCLUSIVE")


@pytest.mark.parametrize("governance,trigger", [
    (guideline(expires=date(2025, 1, 1)), ReevaluationTrigger.GUIDELINE_EXPIRED),
    (guideline(withdrawn=date(2025, 1, 1)), ReevaluationTrigger.GUIDELINE_WITHDRAWN),
    (guideline(superseded="new-guideline"), ReevaluationTrigger.GUIDELINE_SUPERSEDED),
])
def test_guideline_changes_trigger_persistent_reevaluation(tmp_path, governance, trigger):
    engine, packages, _, _, _, _, evidence = persistent_governed(tmp_path, suffix=trigger.value,
                                                                  governance=governance)
    lifecycle = SQLAlchemyGovernedEvidenceLifecycleRepository(engine)
    event = GovernedEvidenceReevaluationService(packages, lifecycle,
        policy_version=evidence.policy_version, appraisal_version=evidence.appraisal_version,
        clock=lambda: NOW).evaluate(evidence, as_of=TODAY)
    assert event.status == GovernedEvidenceLifecycleStatus.REVIEW_REQUIRED
    assert trigger in event.triggers
    assert SQLAlchemyGovernedEvidenceLifecycleRepository(engine).history(evidence.governed_evidence_id) == (event,)


def test_package_revocation_invalidates_governed_evidence(tmp_path):
    engine, packages, package, _, _, _, evidence = persistent_governed(tmp_path, suffix="revoked")
    record = packages._catalog.get(package.package_id)
    relationship = package.claim_evidence_relationships[0]
    record.ledger.append_lifecycle_event(claim_id=relationship.claim_id,
        event_type=LedgerEventType.RETRACTION, target_support_id=relationship.support_id,
        reason="Retracted", occurred_at=NOW)
    event = GovernedEvidenceReevaluationService(packages,
        SQLAlchemyGovernedEvidenceLifecycleRepository(engine),
        policy_version=evidence.policy_version, appraisal_version=evidence.appraisal_version,
        clock=lambda: NOW).evaluate(evidence, as_of=TODAY)
    assert event.status == GovernedEvidenceLifecycleStatus.INVALIDATED
    assert ReevaluationTrigger.PACKAGE_REVOKED in event.triggers


def test_policy_and_appraisal_changes_trigger_review_without_auto_reapproval(tmp_path):
    engine, packages, _, _, _, _, evidence = persistent_governed(tmp_path, suffix="versions")
    lifecycle = SQLAlchemyGovernedEvidenceLifecycleRepository(engine)
    event = GovernedEvidenceReevaluationService(packages, lifecycle,
        policy_version="new-policy", appraisal_version="new-appraisal",
        clock=lambda: NOW).evaluate(evidence, as_of=TODAY)
    assert event.status == GovernedEvidenceLifecycleStatus.REVIEW_REQUIRED
    assert set(event.triggers) >= {
        ReevaluationTrigger.POLICY_VERSION_CHANGED,
        ReevaluationTrigger.APPRAISAL_VERSION_CHANGED,
    }
    assert event.status != GovernedEvidenceLifecycleStatus.ACTIVE


def test_conflict_status_change_triggers_review(tmp_path):
    engine, packages, _, _, _, _, evidence = persistent_governed(tmp_path, suffix="conflict-change")
    event = GovernedEvidenceReevaluationService(packages,
        SQLAlchemyGovernedEvidenceLifecycleRepository(engine),
        policy_version=evidence.policy_version, appraisal_version=evidence.appraisal_version,
        clock=lambda: NOW).evaluate(evidence, as_of=TODAY,
                                    current_conflicts=("CONFLICTING_RECOMMENDATIONS",))
    assert ReevaluationTrigger.CRITICAL_CONFLICT_CHANGED in event.triggers
    assert event.status == GovernedEvidenceLifecycleStatus.REVIEW_REQUIRED
