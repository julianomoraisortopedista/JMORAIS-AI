from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone

import pytest

from jmoraIs.application import (
    EvidencePackageExpired,
    EvidencePackageIntegrityError,
    EvidencePackageNotFound,
    EvidencePackageRejected,
    ExpirationPolicy,
    ScientificEvidencePackagePort,
)
from jmoraIs.evidence_ledger import AppendOnlyEvidenceLedger, hash_payload
from jmoraIs.infrastructure import InMemoryPackageCatalogRepository
from jmoraIs.scientific_domain import (
    ExistenceVerificationStatus,
    IdentifierVerificationResult,
    MetadataReconciliationStatus,
    PublicationVerificationRecord,
    ScientificArticle,
    SourceProvenance,
    VerificationStatus,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def new_port():
    return ScientificEvidencePackagePort(catalog=InMemoryPackageCatalogRepository(), clock=lambda: NOW)


def verified_article(*, provenance=True):
    return ScientificArticle(
        article_id="article-1", title="Verified study", pmid="12345678",
        verification_status=VerificationStatus.VERIFIED.value,
        provenance=SourceProvenance(source_id="provenance-1", source_name="NCBI PubMed") if provenance else None,
        verification_record=PublicationVerificationRecord(
            identifier_results=[IdentifierVerificationResult(
                identifier_type="PMID", identifier_value="12345678", format_valid=True,
                existence_status=ExistenceVerificationStatus.CONFIRMED.value,
                source_name="NCBI PubMed", checked_at=NOW,
            )],
            reconciliation_status=MetadataReconciliationStatus.MATCHED.value,
            final_status=VerificationStatus.VERIFIED.value,
            policy_version="ST-02", search_run_id="search-1", checked_at=NOW,
        ),
    )


def populated_ledger():
    ledger = AppendOnlyEvidenceLedger()
    claim = ledger.create_claim("Treatment improves outcome", claim_id="claim-1", created_at=NOW)
    _, support, _ = ledger.register_evidence(
        claim_id=claim.claim_id, source_name="NCBI PubMed", source_type="pubmed",
        source_locator="https://pubmed.ncbi.nlm.nih.gov/12345678", exact_location="abstract.results",
        passage="Treatment improved outcome.", pmid="12345678",
        payload_hash=hash_payload({"pmid": "12345678"}), retrieved_at=NOW,
        verification_version="ST-02", pipeline_version="ST-03", policy_version="ST-02",
        support_direction="supporting", occurred_at=NOW,
    )
    return ledger, claim.claim_id, support.support_id


def issue(port, *, article=None, ledger=None, expires_at=None):
    actual_ledger, claim_id, support_id = populated_ledger() if ledger is None else ledger
    return port.issue(
        article=article or verified_article(), ledger=actual_ledger, claim_id=claim_id,
        support_ids=(support_id,), pipeline_version="ST-04", expires_at=expires_at,
    )


def test_fake_verified_dictionary_is_rejected():
    port = new_port()
    with pytest.raises(EvidencePackageRejected):
        port.get({"verification_status": "VERIFIED"})
    ledger, claim_id, support_id = populated_ledger()
    with pytest.raises(EvidencePackageRejected):
        port.issue(article={"verification_status": "VERIFIED"}, ledger=ledger, claim_id=claim_id, support_ids=(support_id,), pipeline_version="ST-04")


def test_nonexistent_package_is_rejected():
    with pytest.raises(EvidencePackageNotFound):
        new_port().get("does-not-exist")


def test_tampered_package_is_rejected():
    port = new_port()
    package = issue(port)
    with pytest.raises(FrozenInstanceError):
        package.policy_version = "forged"
    stored = port._catalog._records[package.package_id]
    port._catalog._records[package.package_id] = replace(stored, package=replace(package, policy_version="forged"))
    with pytest.raises(EvidencePackageIntegrityError):
        port.get(package.package_id)


def test_valid_package_is_accepted_and_linked():
    port = new_port()
    package = issue(port)
    assert port.get(package.package_id) == package
    assert package.verification_status == "VERIFIED"
    assert package.provenance_references == ("provenance-1",)
    assert package.ledger_references and package.verification_references
    assert len(package.integrity_hash) == 64


def test_expired_package_requires_explicit_policy():
    port = new_port()
    package = issue(port, expires_at=NOW - timedelta(seconds=1))
    with pytest.raises(EvidencePackageExpired, match="explicit policy"):
        port.get(package.package_id)
    with pytest.raises(EvidencePackageExpired, match="rejected"):
        port.get(package.package_id, expiration_policy=ExpirationPolicy.REJECT_EXPIRED)
    assert port.get(package.package_id, expiration_policy=ExpirationPolicy.ALLOW_EXPIRED_FOR_REVALIDATION) == package


def test_missing_provenance_blocks_emission():
    port = new_port()
    with pytest.raises(EvidencePackageRejected, match="provenance"):
        issue(port, article=verified_article(provenance=False))


def test_missing_ledger_blocks_emission():
    port = new_port()
    empty = AppendOnlyEvidenceLedger()
    with pytest.raises(EvidencePackageRejected, match="claim is absent"):
        port.issue(article=verified_article(), ledger=empty, claim_id="missing", support_ids=("missing",), pipeline_version="ST-04")


def test_unverified_article_cannot_produce_trusted_package():
    port = new_port()
    ledger, claim_id, support_id = populated_ledger()
    unverified = verified_article()
    unverified.verification_status = VerificationStatus.NOT_VERIFIED.value
    with pytest.raises(EvidencePackageRejected, match="VERIFIED"):
        port.issue(article=unverified, ledger=ledger, claim_id=claim_id, support_ids=(support_id,), pipeline_version="ST-06")
