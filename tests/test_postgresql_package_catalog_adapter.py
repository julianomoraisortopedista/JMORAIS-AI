from sqlalchemy import create_engine

from jmoraIs.application import PackageLifecycle, ScientificEvidencePackagePort
from jmoraIs.infrastructure.postgresql_package_catalog import (
    PackageCatalogBase,
    PostgreSQLCanonicalLedger,
    PostgreSQLPackageCatalogRepository,
)
from tests.test_evidence_package_boundary import NOW, populated_ledger, verified_article


def test_sqlalchemy_adapter_recovers_package_and_ledger_after_restart():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    PackageCatalogBase.metadata.create_all(engine)
    repository = PostgreSQLPackageCatalogRepository(engine)
    source, claim_id, support_id = populated_ledger()
    ledger = PostgreSQLCanonicalLedger(engine)
    claim = source.claims[0]
    ledger.create_claim(claim.claim_text, claim_id=claim.claim_id, created_at=claim.created_at)
    fragment = source.fragments[0]
    ledger.register_evidence(claim_id=claim_id, source_name=fragment.source_name, source_type=fragment.source_type, passage=fragment.passage, payload_hash=fragment.payload_hash, retrieved_at=fragment.retrieved_at, verification_version=fragment.verification_version, pipeline_version=fragment.pipeline_version, policy_version=fragment.policy_version, support_direction=source.supports[0].support_direction, source_locator=fragment.source_locator, exact_location=fragment.exact_location, pmid=fragment.pmid, doi=fragment.doi, pmcid=fragment.pmcid, occurred_at=fragment.created_at)
    first = ScientificEvidencePackagePort(catalog=repository, clock=lambda: NOW)
    package = first.issue(
        article=verified_article(), ledger=ledger, claim_id=claim_id,
        support_ids=(support_id,), pipeline_version="ST-09",
    )
    restarted_repository = PostgreSQLPackageCatalogRepository(engine)
    restarted = ScientificEvidencePackagePort(catalog=restarted_repository, clock=lambda: NOW)
    assert restarted.get(package.package_id) == package
    assert restarted.lifecycle(package.package_id) == PackageLifecycle.ACTIVE
    stored = restarted_repository.get(package.package_id)
    assert stored.association.support_ids == (support_id,)
    assert stored.ledger.verify_integrity()
    assert stored.ledger.reconstruct(claim_id).events == ledger.events
    assert len(restarted_repository.version_history(package.package_id)) == 1


def test_package_reread_replays_only_its_signed_claim_scope():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    PackageCatalogBase.metadata.create_all(engine)
    repository = PostgreSQLPackageCatalogRepository(engine)
    source, claim_id, support_id = populated_ledger()
    ledger = PostgreSQLCanonicalLedger(engine)
    claim = source.claims[0]
    ledger.create_claim(claim.claim_text, claim_id=claim.claim_id, created_at=claim.created_at)
    fragment = source.fragments[0]
    ledger.register_evidence(
        claim_id=claim_id, source_name=fragment.source_name,
        source_type=fragment.source_type, passage=fragment.passage,
        payload_hash=fragment.payload_hash, retrieved_at=fragment.retrieved_at,
        verification_version=fragment.verification_version,
        pipeline_version=fragment.pipeline_version, policy_version=fragment.policy_version,
        support_direction=source.supports[0].support_direction,
        source_locator=fragment.source_locator, exact_location=fragment.exact_location,
        pmid=fragment.pmid, doi=fragment.doi, pmcid=fragment.pmcid,
        occurred_at=fragment.created_at,
    )
    unrelated = ledger.create_claim("Unrelated benchmark claim")
    ledger.register_evidence(
        claim_id=unrelated.claim_id, source_name="unrelated", source_type="journal",
        passage="Unrelated evidence", payload_hash="b" * 64,
        retrieved_at=NOW, verification_version="v1", pipeline_version="ST-09",
        policy_version="scientific-evidence-v1",
        support_direction=source.supports[0].support_direction,
        source_locator="unrelated:1", exact_location="p. 1", pmid="99999999",
        occurred_at=NOW,
    )
    package = ScientificEvidencePackagePort(catalog=repository, clock=lambda: NOW).issue(
        article=verified_article(), ledger=ledger, claim_id=claim_id,
        support_ids=(support_id,), pipeline_version="ST-09",
    )

    stored = PostgreSQLPackageCatalogRepository(engine).get(package.package_id)

    assert tuple(item.claim_id for item in stored.ledger.claims) == (claim_id,)
    assert all(item.claim_id == claim_id for item in stored.ledger.supports)
    assert all(item.claim_id == claim_id for item in stored.ledger.events)
    assert stored.ledger.verify_integrity()
