from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from jmoraIs.application import EvidencePackage, ScientificEvidencePackagePort
from jmoraIs.application.scientific_verification import (
    AuthoritativeReconciliationPipeline,
    ScientificVerificationInput,
)
from jmoraIs.evidence_ledger import AppendOnlyEvidenceLedger, hash_payload
from jmoraIs.infrastructure import InMemoryPackageCatalogRepository
from jmoraIs.scientific_domain import (
    ExistenceVerificationStatus,
    IdentifierType,
    IdentifierVerificationResult,
    MetadataReconciliationStatus,
    VerificationStatus,
)


NOW = datetime(2026, 8, 9, 15, 0, tzinfo=timezone.utc)


def authoritative_result(
    identifier_type: IdentifierType,
    identifier: str,
    *,
    source: str,
    metadata: dict[str, Any] | None,
    status: ExistenceVerificationStatus = ExistenceVerificationStatus.CONFIRMED,
) -> IdentifierVerificationResult:
    return IdentifierVerificationResult(
        identifier_type=identifier_type.value,
        identifier_value=identifier,
        format_valid=True,
        existence_status=status.value,
        source_name=source,
        source_locator=(
            f"https://pubmed.ncbi.nlm.nih.gov/{identifier}/"
            if source == "NCBI PubMed"
            else f"https://doi.org/{identifier}"
        ),
        checked_at=NOW,
        raw_outcome={"source": source, "identifier": identifier, "status": status.value},
        authoritative_metadata=metadata,
        error_code=None if status == ExistenceVerificationStatus.CONFIRMED else status.value,
    )


def full_metadata(
    *, pmid: str = "12345678", doi: str | None = "10.1234/canonical"
) -> dict[str, Any]:
    return {
        "pmid": pmid,
        "doi": doi,
        "title": "Canonical scientific publication",
        "journal": "Evidence Journal",
        "year": 2025,
        "authors": ["Jane Doe", "John Smith"],
    }


class MockPubMed:
    def __init__(self, results: list[IdentifierVerificationResult]):
        self.results = results
        self.calls: list[tuple[str, str]] = []

    def search_by_pmid(self, pmid: str) -> IdentifierVerificationResult:
        self.calls.append(("pmid", pmid))
        return self.results[0]

    def search_by_doi(self, doi: str) -> IdentifierVerificationResult:
        self.calls.append(("doi", doi))
        return self.results[0]

    def search_by_title(self, title: str) -> list[IdentifierVerificationResult]:
        self.calls.append(("title", title))
        return self.results


class MockCrossref:
    def __init__(self, results: list[IdentifierVerificationResult]):
        self.results = results
        self.calls: list[str] = []

    def search_by_doi(self, doi: str) -> IdentifierVerificationResult:
        self.calls.append(doi)
        if len(self.results) == 1:
            return self.results[0]
        return self.results[len(self.calls) - 1]


def pipeline(
    pubmed_results: list[IdentifierVerificationResult],
    crossref_results: list[IdentifierVerificationResult] | None = None,
) -> tuple[AuthoritativeReconciliationPipeline, MockPubMed, MockCrossref]:
    pubmed = MockPubMed(pubmed_results)
    crossref = MockCrossref(crossref_results or [])
    use_case = AuthoritativeReconciliationPipeline(
        pubmed=pubmed,
        crossref=crossref,
        clock=lambda: NOW,
    )
    return use_case, pubmed, crossref


def pubmed_result(metadata: dict[str, Any]) -> IdentifierVerificationResult:
    return authoritative_result(
        IdentifierType.PMID,
        str(metadata["pmid"]),
        source="NCBI PubMed",
        metadata=metadata,
    )


def crossref_result(
    metadata: dict[str, Any],
    *,
    status: ExistenceVerificationStatus = ExistenceVerificationStatus.CONFIRMED,
) -> IdentifierVerificationResult:
    return authoritative_result(
        IdentifierType.DOI,
        str(metadata["doi"]),
        source="Crossref",
        metadata=metadata if status == ExistenceVerificationStatus.CONFIRMED else None,
        status=status,
    )


def test_full_match_is_eligible_and_associates_pmid_with_doi() -> None:
    metadata = full_metadata()
    use_case, pubmed, crossref = pipeline(
        [pubmed_result(metadata)], [crossref_result(metadata)]
    )

    result = use_case._execute_internal(ScientificVerificationInput(pmid="12345678"))

    article = result.articles[0]
    assert pubmed.calls == [("pmid", "12345678")]
    assert crossref.calls == ["10.1234/canonical"]
    assert article.pmid == "12345678"
    assert article.doi == "10.1234/canonical"
    assert article.verification_status == VerificationStatus.VERIFIED.value
    assert article.verification_record.reconciliation_status == "MATCHED"
    assert article.verification_record.search_run_id == result.search_run.search_id
    assert result.eligible_articles == (article,)
    assert article.provenance.raw_payload["source"] == "NCBI PubMed"
    assert all(item.raw_outcome for item in article.verification_record.identifier_results)


def test_verified_pipeline_output_crosses_boundary_only_as_package() -> None:
    metadata = full_metadata()
    pubmed = MockPubMed([pubmed_result(metadata)])
    crossref = MockCrossref([crossref_result(metadata)])
    packages = ScientificEvidencePackagePort(catalog=InMemoryPackageCatalogRepository(), clock=lambda: NOW)
    use_case = AuthoritativeReconciliationPipeline(
        pubmed=pubmed, crossref=crossref, packages=packages, clock=lambda: NOW,
    )
    ledger = AppendOnlyEvidenceLedger()
    claim = ledger.create_claim("Canonical claim", claim_id="claim-package", created_at=NOW)
    _, support, _ = ledger.register_evidence(
        claim_id=claim.claim_id, source_name="NCBI PubMed", source_type="pubmed",
        passage="Canonical result", pmid="12345678", doi="10.1234/canonical",
        payload_hash=hash_payload(metadata), retrieved_at=NOW,
        verification_version="ST-02", pipeline_version="ST-06", policy_version="ST-02",
        support_direction="supporting", occurred_at=NOW,
    )
    issued = use_case.issue_trusted(
        ScientificVerificationInput(pmid="12345678"), ledger=ledger,
        claim_id=claim.claim_id, support_ids=(support.support_id,), pipeline_version="ST-06",
    )
    assert len(issued) == 1
    assert isinstance(issued[0], EvidencePackage)
    assert packages.get(issued[0].package_id) == issued[0]


def test_doi_input_uses_pubmed_first_and_associates_resolved_pmid() -> None:
    metadata = full_metadata()
    use_case, pubmed, crossref = pipeline(
        [pubmed_result(metadata)], [crossref_result(metadata)]
    )

    result = use_case._execute_internal(ScientificVerificationInput(doi="10.1234/canonical"))

    article = result.articles[0]
    assert pubmed.calls == [("doi", "10.1234/canonical")]
    assert crossref.calls == ["10.1234/canonical"]
    assert (article.pmid, article.doi) == ("12345678", "10.1234/canonical")
    assert article.verification_status == VerificationStatus.VERIFIED.value
    assert result.eligible_articles == (article,)


def test_partial_match_is_preserved_but_not_eligible() -> None:
    pubmed_metadata = full_metadata()
    crossref_metadata = {**full_metadata(), "authors": []}
    use_case, _, _ = pipeline(
        [pubmed_result(pubmed_metadata)], [crossref_result(crossref_metadata)]
    )

    result = use_case._execute_internal(ScientificVerificationInput(pmid="12345678"))

    article = result.articles[0]
    assert article.verification_status == VerificationStatus.PARTIALLY_VERIFIED.value
    assert article.verification_record.reconciliation_status == MetadataReconciliationStatus.PARTIAL_MATCH.value
    assert "Crossref:authors" in article.verification_record.metadata_missing
    assert result.eligible_articles == ()


def test_incompatible_doi_is_conflicting_and_preserved() -> None:
    pubmed_metadata = full_metadata()
    incompatible = {**full_metadata(), "doi": "10.9999/different"}
    crossref = authoritative_result(
        IdentifierType.DOI,
        "10.1234/canonical",
        source="Crossref",
        metadata=incompatible,
    )
    use_case, _, _ = pipeline([pubmed_result(pubmed_metadata)], [crossref])

    result = use_case._execute_internal(ScientificVerificationInput(pmid="12345678"))

    article = result.articles[0]
    assert article.verification_status == VerificationStatus.CONFLICTING_METADATA.value
    assert "Crossref:doi" in article.verification_record.metadata_conflicts
    assert article.verification_record.identifier_results[1].authoritative_metadata["doi"] == "10.9999/different"
    assert result.eligible_articles == ()


def test_incompatible_pmid_is_conflicting_and_preserved() -> None:
    incompatible = full_metadata(pmid="87654321", doi=None)
    pubmed = authoritative_result(
        IdentifierType.PMID,
        "12345678",
        source="NCBI PubMed",
        metadata=incompatible,
    )
    use_case, _, _ = pipeline([pubmed])

    result = use_case._execute_internal(ScientificVerificationInput(pmid="12345678"))

    article = result.articles[0]
    assert article.verification_status == VerificationStatus.CONFLICTING_METADATA.value
    assert "NCBI PubMed:pmid" in article.verification_record.metadata_conflicts
    assert result.eligible_articles == ()


def test_duplicate_is_merged_with_traceable_decision_and_both_provenances_retained() -> None:
    metadata = full_metadata()
    first = pubmed_result(metadata)
    second = pubmed_result(metadata)
    first = replace(first, source_locator="https://pubmed.ncbi.nlm.nih.gov/12345678/?record=1")
    second = replace(second, source_locator="https://pubmed.ncbi.nlm.nih.gov/12345678/?record=2")
    use_case, _, _ = pipeline(
        [first, second],
        [crossref_result(metadata), crossref_result(metadata)],
    )

    result = use_case._execute_internal(ScientificVerificationInput(query="canonical publication"))

    assert len(result.articles) == 2
    assert len(result.eligible_articles) == 1
    assert len(result.deduplication_decisions) == 1
    decision = result.deduplication_decisions[0]
    assert decision.deduplication_key == "doi|10.1234/canonical"
    assert decision.kept_provenance_id
    assert decision.duplicate_provenance_id
    assert decision.kept_provenance_id != decision.duplicate_provenance_id
    assert {article.provenance.source_locator for article in result.articles} == {
        first.source_locator,
        second.source_locator,
    }


def test_absent_crossref_is_not_called_when_pubmed_has_no_doi() -> None:
    metadata = full_metadata(doi=None)
    use_case, _, crossref = pipeline([pubmed_result(metadata)])

    result = use_case._execute_internal(ScientificVerificationInput(pmid="12345678"))

    assert crossref.calls == []
    assert result.articles[0].verification_status == VerificationStatus.VERIFIED.value
    assert result.eligible_articles == result.articles


def test_temporary_crossref_unavailability_degrades_and_blocks() -> None:
    metadata = full_metadata()
    unavailable = crossref_result(
        metadata, status=ExistenceVerificationStatus.SOURCE_UNAVAILABLE
    )
    use_case, _, _ = pipeline([pubmed_result(metadata)], [unavailable])

    result = use_case._execute_internal(ScientificVerificationInput(pmid="12345678"))

    assert result.search_run.status == "DEGRADED"
    assert result.articles[0].verification_status == VerificationStatus.NOT_VERIFIED.value
    assert result.articles[0].verification_record.identifier_results[1].raw_outcome
    assert result.eligible_articles == ()


def test_conflicting_metadata_is_never_hidden() -> None:
    pubmed_metadata = full_metadata()
    crossref_metadata = {
        **full_metadata(),
        "title": "Different title",
        "journal": "Different Journal",
        "year": 2024,
        "authors": ["Different Author"],
    }
    use_case, _, _ = pipeline(
        [pubmed_result(pubmed_metadata)], [crossref_result(crossref_metadata)]
    )

    result = use_case._execute_internal(ScientificVerificationInput(pmid="12345678"))

    conflicts = result.articles[0].verification_record.metadata_conflicts
    assert conflicts == (
        "Crossref:title",
        "Crossref:journal",
        "Crossref:year",
        "Crossref:authors",
    )
    assert result.eligible_articles == ()
