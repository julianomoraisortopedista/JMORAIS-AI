from datetime import timedelta

import pytest

from jmoraIs.application import (
    EvidencePackageRevoked,
    PackageLifecycle,
    ScientificEvidencePackagePort,
)
from jmoraIs.clinical import DeprecatedClinicalPathError
from jmoraIs.clinical_engine import ClinicalDecisionEngine
from jmoraIs.evidence_ledger import LedgerEventType
from jmoraIs.infrastructure import InMemoryPackageCatalogRepository
from tests.test_evidence_package_boundary import NOW, populated_ledger, verified_article


def setup_package():
    current = [NOW]
    port = ScientificEvidencePackagePort(catalog=InMemoryPackageCatalogRepository(), clock=lambda: current[0])
    ledger, claim_id, support_id = populated_ledger()
    package = port.issue(
        article=verified_article(), ledger=ledger, claim_id=claim_id,
        support_ids=(support_id,), pipeline_version="ST-07",
    )
    return current, port, ledger, claim_id, support_id, package


def append_event(current, ledger, claim_id, support_id, event_type):
    occurred_at = NOW + timedelta(minutes=1)
    ledger.append_lifecycle_event(
        claim_id=claim_id, event_type=event_type, target_support_id=support_id,
        reason=f"test {event_type}", occurred_at=occurred_at,
    )
    current[0] = occurred_at


def test_package_is_initially_active():
    _, port, _, _, _, package = setup_package()
    assert port.lifecycle(package.package_id) == PackageLifecycle.ACTIVE
    assert port.get(package.package_id) == package


def test_retraction_automatically_revokes_existing_package():
    current, port, ledger, claim_id, support_id, package = setup_package()
    original_events = ledger.events
    append_event(current, ledger, claim_id, support_id, LedgerEventType.RETRACTION)
    assert port.lifecycle(package.package_id) == PackageLifecycle.RETRACTED
    with pytest.raises(EvidencePackageRevoked) as error:
        port.get(package.package_id)
    assert error.value.lifecycle == PackageLifecycle.RETRACTED
    assert ledger.events[:-1] == original_events


def test_invalidation_automatically_revokes_existing_package():
    current, port, ledger, claim_id, support_id, package = setup_package()
    append_event(current, ledger, claim_id, support_id, LedgerEventType.INVALIDATION)
    assert port.lifecycle(package.package_id) == PackageLifecycle.INVALIDATED
    with pytest.raises(EvidencePackageRevoked):
        port.get(package.package_id)


def test_supersession_rejects_old_package_and_accepts_new_package():
    current, port, ledger, claim_id, old_support_id, old_package = setup_package()
    _, new_support, _ = ledger.register_evidence(
        claim_id=claim_id, source_name="NCBI PubMed", source_type="pubmed",
        passage="Updated result", pmid="12345678", payload_hash="b" * 64,
        retrieved_at=NOW + timedelta(seconds=30), verification_version="ST-02",
        pipeline_version="ST-07", policy_version="ST-02", support_direction="supporting",
        occurred_at=NOW + timedelta(seconds=30),
    )
    ledger.append_lifecycle_event(
        claim_id=claim_id, event_type=LedgerEventType.SUPERSESSION,
        target_support_id=old_support_id, replacement_support_id=new_support.support_id,
        reason="new evidence fragment", occurred_at=NOW + timedelta(minutes=1),
    )
    current[0] = NOW + timedelta(minutes=1)
    new_package = port.issue(
        article=verified_article(), ledger=ledger, claim_id=claim_id,
        support_ids=(new_support.support_id,), pipeline_version="ST-07",
    )
    assert port.lifecycle(old_package.package_id) == PackageLifecycle.SUPERSEDED
    with pytest.raises(EvidencePackageRevoked):
        port.get(old_package.package_id)
    assert port.lifecycle(new_package.package_id) == PackageLifecycle.ACTIVE
    assert port.get(new_package.package_id) == new_package


def test_historical_reconstruction_and_ledger_replay_preserve_prior_validity():
    current, port, ledger, claim_id, support_id, package = setup_package()
    original_event = ledger.events[0]
    append_event(current, ledger, claim_id, support_id, LedgerEventType.RETRACTION)
    historical_time = NOW + timedelta(seconds=30)
    assert port.lifecycle(package.package_id, as_of=historical_time) == PackageLifecycle.ACTIVE
    assert port.get(package.package_id, as_of=historical_time) == package
    assert port.lifecycle(package.package_id) == PackageLifecycle.RETRACTED
    assert ledger.verify_integrity()
    assert ledger.reconstruct(claim_id, as_of=historical_time).events == (original_event,)
    assert ledger.events[0] == original_event


@pytest.mark.parametrize(
    ("event_type", "expected"),
    [
        (LedgerEventType.RETRACTION, PackageLifecycle.RETRACTED),
        (LedgerEventType.INVALIDATION, PackageLifecycle.INVALIDATED),
        (LedgerEventType.SUPERSESSION, PackageLifecycle.SUPERSEDED),
    ],
)
def test_clinical_engine_refuses_revoked_package(event_type, expected):
    current, port, ledger, claim_id, support_id, package = setup_package()
    if event_type == LedgerEventType.SUPERSESSION:
        _, replacement, _ = ledger.register_evidence(
            claim_id=claim_id, source_name="PubMed", source_type="pubmed", passage="replacement",
            pmid="12345678", payload_hash="c" * 64, retrieved_at=NOW,
            verification_version="ST-02", pipeline_version="ST-07", policy_version="ST-02",
            support_direction="supporting", occurred_at=NOW,
        )
        ledger.append_lifecycle_event(
            claim_id=claim_id, event_type=event_type, target_support_id=support_id,
            replacement_support_id=replacement.support_id, occurred_at=NOW + timedelta(minutes=1),
        )
        current[0] = NOW + timedelta(minutes=1)
    else:
        append_event(current, ledger, claim_id, support_id, event_type)
    assert port.lifecycle(package.package_id) == expected
    with pytest.raises(DeprecatedClinicalPathError):
        ClinicalDecisionEngine(port)
