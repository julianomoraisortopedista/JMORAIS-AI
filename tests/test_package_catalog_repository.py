from datetime import timedelta

import pytest

from jmoraIs.application import EvidencePackageRevoked, PackageLifecycle, ScientificEvidencePackagePort
from jmoraIs.evidence_ledger import LedgerEventType
from jmoraIs.infrastructure import InMemoryPackageCatalogRepository
from jmoraIs.infrastructure.package_catalog import PackageCatalogConflict
from tests.test_evidence_package_boundary import NOW, populated_ledger, verified_article


def issue_with_catalog(catalog, clock):
    ledger, claim_id, support_id = populated_ledger()
    port = ScientificEvidencePackagePort(catalog=catalog, clock=clock)
    package = port.issue(
        article=verified_article(), ledger=ledger, claim_id=claim_id,
        support_ids=(support_id,), pipeline_version="ST-08",
    )
    return port, package, ledger, claim_id, support_id


def test_package_persists_and_is_retrievable_after_port_restart():
    catalog = InMemoryPackageCatalogRepository()
    _, package, _, _, _ = issue_with_catalog(catalog, lambda: NOW)
    restarted = ScientificEvidencePackagePort(catalog=catalog, clock=lambda: NOW)
    assert restarted.get(package.package_id) == package


def test_ledger_association_and_version_history_are_persisted():
    catalog = InMemoryPackageCatalogRepository()
    _, package, _, claim_id, support_id = issue_with_catalog(catalog, lambda: NOW)
    stored = catalog.get(package.package_id)
    assert stored.association.claim_ids == (claim_id,)
    assert stored.association.support_ids == (support_id,)
    assert stored.association.ledger_event_hashes == package.ledger_references
    versions = catalog.version_history(package.package_id)
    assert [(item.package_version, item.integrity_hash) for item in versions] == [
        (package.package_version, package.integrity_hash)
    ]


def test_lifecycle_transition_persists_across_restart():
    current = [NOW]
    catalog = InMemoryPackageCatalogRepository()
    _, package, ledger, claim_id, support_id = issue_with_catalog(catalog, lambda: current[0])
    ledger.append_lifecycle_event(
        claim_id=claim_id, event_type=LedgerEventType.RETRACTION,
        target_support_id=support_id, occurred_at=NOW + timedelta(minutes=1),
    )
    current[0] = NOW + timedelta(minutes=1)
    restarted = ScientificEvidencePackagePort(catalog=catalog, clock=lambda: current[0])
    with pytest.raises(EvidencePackageRevoked):
        restarted.get(package.package_id)
    assert restarted.lifecycle(package.package_id) == PackageLifecycle.RETRACTED


def test_historical_replay_survives_restart_without_overwriting_history():
    current = [NOW]
    catalog = InMemoryPackageCatalogRepository()
    _, package, ledger, claim_id, support_id = issue_with_catalog(catalog, lambda: current[0])
    original_events = ledger.events
    ledger.append_lifecycle_event(
        claim_id=claim_id, event_type=LedgerEventType.INVALIDATION,
        target_support_id=support_id, occurred_at=NOW + timedelta(minutes=2),
    )
    current[0] = NOW + timedelta(minutes=2)
    restarted = ScientificEvidencePackagePort(catalog=catalog, clock=lambda: current[0])
    assert restarted.lifecycle(package.package_id) == PackageLifecycle.INVALIDATED
    assert restarted.lifecycle(package.package_id, as_of=NOW + timedelta(minutes=1)) == PackageLifecycle.ACTIVE
    assert ledger.events[:-1] == original_events
    assert ledger.verify_integrity()


def test_catalog_is_append_only_and_rejects_overwrite():
    catalog = InMemoryPackageCatalogRepository()
    _, package, _, _, _ = issue_with_catalog(catalog, lambda: NOW)
    record = catalog.get(package.package_id)
    version = catalog.version_history(package.package_id)[0]
    with pytest.raises(PackageCatalogConflict, match="overwritten"):
        catalog.append(record, version)
    assert not hasattr(catalog, "delete")
    assert not hasattr(catalog, "update")
