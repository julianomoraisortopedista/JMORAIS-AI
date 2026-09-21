from dataclasses import replace

import pytest

from jmoraIs.appraisal import (
    ClinicalAppraisalPersistenceService, ClinicalAppraisalService, GovernedEvidenceService,
    InMemoryClinicalAppraisalRepository, InMemoryGovernedEvidenceRepository,
)
from jmoraIs.audit_defense import AuditDefenseBoundaryRejected, CanonicalGovernedAuditEvidenceAdapter
from jmoraIs.clinical import GovernedEvidenceReevaluationService, InMemoryGovernedEvidenceLifecycleRepository
from jmoraIs.evidence_ledger import LedgerEventType
from tests.test_clinical_appraisal_domain import TODAY, request
from tests.test_clinical_appraisal_persistence import NOW
from tests.test_clinical_intelligence_foundation import issue_direction, package_port
from tests.test_evidence_package_boundary import NOW as PACKAGE_NOW


def governed(direction="supporting", suffix="audit-evidence"):
    packages = package_port(); package = issue_direction(packages, direction, suffix)
    source = request(identifier=f"rec-{suffix}", package_id=package.package_id)
    appraisal_repository = InMemoryClinicalAppraisalRepository()
    appraisals = ClinicalAppraisalPersistenceService(
        ClinicalAppraisalService(packages), appraisal_repository, clock=lambda: NOW,
    )
    record = appraisals.assess_and_persist((source,), as_of=TODAY)[0][0]
    evidence_repository = InMemoryGovernedEvidenceRepository()
    evidence_service = GovernedEvidenceService(
        packages, evidence_repository, appraisals=appraisal_repository, clock=lambda: NOW,
    )
    evidence = evidence_service.issue_persisted(record.appraisal_id)
    lifecycle = GovernedEvidenceReevaluationService(
        packages, InMemoryGovernedEvidenceLifecycleRepository(),
        policy_version=evidence.policy_version, appraisal_version=evidence.appraisal_version,
        clock=lambda: NOW,
    )
    adapter = CanonicalGovernedAuditEvidenceAdapter(evidence_service, lifecycle, appraisals)
    return adapter, evidence, record, package, packages, evidence_repository, appraisal_repository


@pytest.mark.parametrize("direction", ("supporting", "opposing", "neutral", "inconclusive"))
def test_canonical_directions_are_preserved_without_reinterpretation(direction):
    adapter, evidence, *_ = governed(direction, f"direction-{direction}")
    assert adapter.get(evidence.governed_evidence_id).support_directions == (direction.upper(),)


def test_missing_forged_and_incomplete_evidence_fail_closed():
    adapter, evidence, _, _, _, repository, _ = governed()
    with pytest.raises(AuditDefenseBoundaryRejected): adapter.get("missing")
    with pytest.raises(AuditDefenseBoundaryRejected): adapter.get({"governed_evidence_id": evidence.governed_evidence_id})
    repository._items[evidence.governed_evidence_id] = replace(evidence, provenance_references=())
    with pytest.raises(AuditDefenseBoundaryRejected): adapter.get(evidence.governed_evidence_id)


def test_missing_ledger_integrity_and_appraisal_linkage_fail_closed():
    adapter, evidence, record, _, _, repository, appraisals = governed(suffix="negative-linkage")
    repository._items[evidence.governed_evidence_id] = replace(evidence, ledger_references=())
    with pytest.raises(AuditDefenseBoundaryRejected): adapter.get(evidence.governed_evidence_id)
    repository._items[evidence.governed_evidence_id] = replace(evidence, integrity_hash="0" * 64)
    with pytest.raises(AuditDefenseBoundaryRejected): adapter.get(evidence.governed_evidence_id)
    repository._items[evidence.governed_evidence_id] = evidence
    del appraisals._items[record.appraisal_id]
    with pytest.raises(AuditDefenseBoundaryRejected): adapter.get(evidence.governed_evidence_id)


def test_invalid_appraisal_linkage_and_inactive_lifecycle_fail_closed():
    adapter, evidence, record, _, _, _, appraisals = governed(suffix="invalid-appraisal")
    appraisals._items[record.appraisal_id] = replace(record, integrity_hash="0" * 64)
    with pytest.raises(AuditDefenseBoundaryRejected): adapter.get(evidence.governed_evidence_id)
    adapter, evidence, *_ = governed(suffix="inactive")
    adapter._lifecycle = type("Lifecycle", (), {"current_status": lambda self, value: "SUPERSEDED"})()
    with pytest.raises(AuditDefenseBoundaryRejected): adapter.get(evidence.governed_evidence_id)


def test_revoked_package_is_rejected_by_canonical_package_validation():
    adapter, evidence, _, package, packages, *_ = governed(suffix="revoked")
    stored = packages._catalog.get(package.package_id); relationship = package.claim_evidence_relationships[0]
    stored.ledger.append_lifecycle_event(
        claim_id=relationship.claim_id, event_type=LedgerEventType.RETRACTION,
        target_support_id=relationship.support_id, reason="Retracted", occurred_at=PACKAGE_NOW,
    )
    with pytest.raises(AuditDefenseBoundaryRejected): adapter.get(evidence.governed_evidence_id)
