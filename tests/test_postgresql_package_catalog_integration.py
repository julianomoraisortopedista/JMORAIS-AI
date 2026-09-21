import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from jmoraIs.application import EvidencePackageRevoked, PackageLifecycle, ScientificEvidencePackagePort
from jmoraIs.evidence_ledger import LedgerEventType
from jmoraIs.infrastructure.postgresql_package_catalog import PostgreSQLCanonicalLedger, PostgreSQLPackageCatalogRepository
from jmoraIs.infrastructure.cryptographic_replay import (
    PostgreSQLCryptographicReplayEngine, ReplayIntegrityStatus,
)
from tests.test_evidence_package_boundary import NOW, populated_ledger, verified_article

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def postgres_engine():
    url = os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("JMORAIS_TEST_POSTGRES_URL is required for PostgreSQL integration tests")
    alembic_command = pytest.importorskip("alembic.command")
    from alembic.config import Config

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    alembic_command.upgrade(config, "head")
    engine = create_engine(url, future=True)
    yield engine
    engine.dispose()


def test_postgresql_recovery_append_only_and_historical_replay(postgres_engine):
    repository = PostgreSQLPackageCatalogRepository(postgres_engine)
    source, claim_id, support_id = populated_ledger()
    ledger = PostgreSQLCanonicalLedger(postgres_engine)
    claim, fragment, support = source.claims[0], source.fragments[0], source.supports[0]
    ledger.create_claim(claim.claim_text, claim_id=claim.claim_id, created_at=claim.created_at)
    _, canonical_support, _ = ledger.register_evidence(claim_id=claim_id, source_name=fragment.source_name, source_type=fragment.source_type, passage=fragment.passage, payload_hash=fragment.payload_hash, retrieved_at=fragment.retrieved_at, verification_version=fragment.verification_version, pipeline_version=fragment.pipeline_version, policy_version=fragment.policy_version, support_direction=support.support_direction, source_locator=fragment.source_locator, exact_location=fragment.exact_location, pmid=fragment.pmid, occurred_at=fragment.created_at)
    support_id = canonical_support.support_id
    port = ScientificEvidencePackagePort(catalog=repository, clock=lambda: NOW)
    package = port.issue(
        article=verified_article(), ledger=ledger, claim_id=claim_id,
        support_ids=(support_id,), pipeline_version="ST-09-PG",
    )

    restarted = ScientificEvidencePackagePort(
        catalog=PostgreSQLPackageCatalogRepository(postgres_engine), clock=lambda: NOW,
    )
    assert restarted.get(package.package_id) == package
    assert restarted.lifecycle(package.package_id, as_of=NOW) == PackageLifecycle.ACTIVE
    recovered = restarted._catalog.get(package.package_id)
    assert recovered.association.ledger_event_hashes == package.ledger_references
    assert recovered.ledger.verify_integrity()
    assert recovered.ledger.reconstruct(claim_id, as_of=NOW).events == ledger.events
    assert PostgreSQLCryptographicReplayEngine(postgres_engine).replay_evidence_package(
        package.package_id
    ).integrity_status == ReplayIntegrityStatus.VALID

    _, replacement, _ = ledger.register_evidence(claim_id=claim_id, source_name="PubMed", source_type="pubmed", passage="replacement", payload_hash="d" * 64, retrieved_at=NOW, verification_version="ST-10", pipeline_version="ST-10", policy_version="ST-02", support_direction="supporting", pmid="12345678", occurred_at=NOW)
    ledger.append_lifecycle_event(claim_id=claim_id, event_type=LedgerEventType.SUPERSESSION, target_support_id=support_id, replacement_support_id=replacement.support_id, occurred_at=NOW)
    replacement_package = port.issue(article=verified_article(), ledger=ledger, claim_id=claim_id, support_ids=(replacement.support_id,), pipeline_version="ST-10")
    replayed = ScientificEvidencePackagePort(catalog=PostgreSQLPackageCatalogRepository(postgres_engine), clock=lambda: NOW)
    assert replayed.lifecycle(package.package_id) == PackageLifecycle.SUPERSEDED
    assert replayed.get(replacement_package.package_id) == replacement_package

    ledger.append_lifecycle_event(claim_id=claim_id, event_type=LedgerEventType.RETRACTION, target_support_id=replacement.support_id, occurred_at=NOW)
    replayed = ScientificEvidencePackagePort(catalog=PostgreSQLPackageCatalogRepository(postgres_engine), clock=lambda: NOW)
    assert replayed.lifecycle(replacement_package.package_id) == PackageLifecycle.RETRACTED
    with pytest.raises(EvidencePackageRevoked): replayed.get(replacement_package.package_id)

    _, invalidated_support, _ = ledger.register_evidence(claim_id=claim_id, source_name="PubMed", source_type="pubmed", passage="invalidated", payload_hash="e" * 64, retrieved_at=NOW, verification_version="ST-10", pipeline_version="ST-10", policy_version="ST-02", support_direction="supporting", pmid="12345678", occurred_at=NOW)
    invalidated_package = port.issue(article=verified_article(), ledger=ledger, claim_id=claim_id, support_ids=(invalidated_support.support_id,), pipeline_version="ST-10")
    ledger.append_lifecycle_event(claim_id=claim_id, event_type=LedgerEventType.INVALIDATION, target_support_id=invalidated_support.support_id, occurred_at=NOW)
    replayed = ScientificEvidencePackagePort(catalog=PostgreSQLPackageCatalogRepository(postgres_engine), clock=lambda: NOW)
    assert replayed.lifecycle(invalidated_package.package_id) == PackageLifecycle.INVALIDATED

    with postgres_engine.begin() as connection:
        with pytest.raises(DBAPIError):
            connection.execute(text("UPDATE evidence_package_catalog SET package_id = package_id WHERE package_id = :id"), {"id": package.package_id})
    with postgres_engine.begin() as connection:
        with pytest.raises(DBAPIError):
            connection.execute(text("DELETE FROM evidence_package_catalog WHERE package_id = :id"), {"id": package.package_id})
