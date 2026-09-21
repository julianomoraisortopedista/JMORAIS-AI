from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone

import pytest

from jmoraIs.appraisal import (
    AppraisalRecordStatus,
    ClinicalAppraisalPersistenceService,
    ClinicalAppraisalService,
    GovernedEvidenceError,
    GovernedEvidenceService,
    InMemoryClinicalAppraisalRepository,
    InMemoryGovernedEvidenceRepository,
)
from tests.test_clinical_appraisal_domain import TODAY, guideline, request
from tests.test_clinical_intelligence_foundation import issue_direction, package_port


NOW = datetime(2026, 1, 2, tzinfo=timezone.utc)


def workflow(*, governance=None):
    packages = package_port()
    package = issue_direction(packages, "supporting", "persistent-appraisal")
    source = request(package_id=package.package_id, governance=governance)
    repository = InMemoryClinicalAppraisalRepository()
    service = ClinicalAppraisalPersistenceService(
        ClinicalAppraisalService(packages), repository, clock=lambda: NOW,
    )
    return packages, source, repository, service


def test_canonical_appraisal_is_immutable_versioned_and_traceable():
    _, source, repository, service = workflow()
    first = service.assess_and_persist((source,), as_of=TODAY)[0][0]
    second = service.assess_and_persist((source,), as_of=TODAY)[0][0]

    assert first.status is AppraisalRecordStatus.ELIGIBLE
    assert first.appraisal_version == 1
    assert second.appraisal_version == 2
    assert second.predecessor_appraisal_id == first.appraisal_id
    assert repository.history(source.recommendation_id) == (first, second)
    assert repository.by_evidence_package(source.evidence_package_id) == (first, second)
    assert first.provenance_references
    assert first.framework_version == "ST-13.1"
    with pytest.raises(FrozenInstanceError):
        first.policy_version = "tampered"


def test_repository_is_append_only_and_rejects_invalid_version_chain():
    _, source, repository, service = workflow()
    first = service.assess_and_persist((source,), as_of=TODAY)[0][0]
    with pytest.raises(ValueError, match="overwrit"):
        repository.append(first)
    with pytest.raises(ValueError, match="predecessor"):
        repository.append(replace(first, appraisal_id="forged", appraisal_version=3,
                                  predecessor_appraisal_id=first.appraisal_id))
    assert not hasattr(repository, "update")
    assert not hasattr(repository, "delete")


def test_governed_evidence_resolves_persisted_appraisal_by_identifier():
    packages, source, appraisals, persistence = workflow()
    record = persistence.assess_and_persist((source,), as_of=TODAY)[0][0]
    service = GovernedEvidenceService(
        packages, InMemoryGovernedEvidenceRepository(), appraisals=appraisals,
        clock=lambda: NOW,
    )
    governed = service.issue_persisted(record.appraisal_id)
    assert governed.appraisal_result_id == record.appraisal_id
    assert governed.evidence_package_id == record.evidence_package_id


def test_untrusted_or_review_required_appraisal_cannot_issue_governed_evidence():
    packages, source, appraisals, persistence = workflow(
        governance=guideline(expires=TODAY.replace(year=2025)),
    )
    record = persistence.assess_and_persist((source,), as_of=TODAY)[0][0]
    service = GovernedEvidenceService(
        packages, InMemoryGovernedEvidenceRepository(), appraisals=appraisals,
    )
    assert record.status is AppraisalRecordStatus.REVIEW_REQUIRED
    with pytest.raises(GovernedEvidenceError, match="not eligible"):
        service.issue_persisted(record.appraisal_id)
    with pytest.raises(GovernedEvidenceError, match="type is invalid"):
        service.issue_persisted("missing")


def test_forged_persisted_appraisal_integrity_is_rejected():
    packages, source, appraisals, persistence = workflow()
    record = persistence.assess_and_persist((source,), as_of=TODAY)[0][0]
    forged = replace(record, appraisal_id="forged-appraisal",
                     recommendation_reference="forged-recommendation", integrity_hash="0" * 64)
    appraisals.append(forged)
    service = GovernedEvidenceService(
        packages, InMemoryGovernedEvidenceRepository(), appraisals=appraisals,
    )
    with pytest.raises(GovernedEvidenceError, match="integrity"):
        service.issue_persisted(forged.appraisal_id)


def test_persisted_artifact_contains_no_patient_or_tenant_payload():
    _, source, _, service = workflow()
    record = service.assess_and_persist((source,), as_of=TODAY)[0][0]
    serialized = repr(record).lower()
    assert "patient_context" not in serialized
    assert "patient_id" not in serialized
    assert "tenant_id" not in serialized
    assert "organization_id" not in serialized
