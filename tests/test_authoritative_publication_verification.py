from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from jmoraIs.scientific_domain import (
    ExistenceVerificationStatus,
    IdentifierType,
    IdentifierVerificationResult,
    MetadataReconciliationStatus,
    ScientificArticle,
    VerificationStatus,
)
from jmoraIs.verification import (
    verify_article_metadata,
    verify_publication_authoritatively,
)


NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)


def outcome(
    identifier_type: IdentifierType,
    identifier: str,
    status: ExistenceVerificationStatus,
    *,
    metadata: dict[str, Any] | None = None,
    source: str | None = None,
    raw: Any = None,
) -> IdentifierVerificationResult:
    source_name = source or ("NCBI PubMed" if identifier_type == IdentifierType.PMID else "Crossref")
    return IdentifierVerificationResult(
        identifier_type=identifier_type.value,
        identifier_value=identifier,
        format_valid=True,
        existence_status=status.value,
        source_name=source_name,
        source_locator=(
            f"https://pubmed.ncbi.nlm.nih.gov/{identifier}/"
            if identifier_type == IdentifierType.PMID
            else f"https://doi.org/{identifier}"
        ),
        checked_at=NOW,
        raw_outcome=raw if raw is not None else {"outcome": status.value},
        authoritative_metadata=metadata,
        error_code=None if status == ExistenceVerificationStatus.CONFIRMED else status.value,
    )


class StubPubMed:
    def __init__(self, result: IdentifierVerificationResult):
        self.result = result

    def search_by_pmid(self, pmid: str) -> IdentifierVerificationResult:
        assert pmid == self.result.identifier_value
        return self.result


class StubCrossref:
    def __init__(self, result: IdentifierVerificationResult):
        self.result = result

    def search_by_doi(self, doi: str) -> IdentifierVerificationResult:
        assert doi == self.result.identifier_value
        return self.result


def unused_pubmed() -> StubPubMed:
    return StubPubMed(outcome(IdentifierType.PMID, "1", ExistenceVerificationStatus.NOT_CHECKED))


def unused_crossref() -> StubCrossref:
    return StubCrossref(outcome(IdentifierType.DOI, "10.1/x", ExistenceVerificationStatus.NOT_CHECKED))


def matching_metadata(*, pmid: str | None = None, doi: str | None = None) -> dict[str, Any]:
    return {
        "pmid": pmid,
        "doi": doi,
        "title": "Authoritative publication",
        "journal": "Evidence Journal",
        "year": 2025,
        "authors": ["Jane Doe"],
    }


def article(**identifiers: str) -> ScientificArticle:
    return ScientificArticle(
        title="Authoritative publication",
        journal="Evidence Journal",
        publication_year=2025,
        authors=["Jane Doe"],
        **identifiers,
    )


def test_syntactically_valid_but_nonexistent_pmid_is_blocked() -> None:
    result = outcome(IdentifierType.PMID, "99999999", ExistenceVerificationStatus.NOT_FOUND)

    verified = verify_publication_authoritatively(
        article(pmid="99999999"),
        pubmed_connector=StubPubMed(result),
        crossref_connector=unused_crossref(),
    )

    assert verified.verification_status == VerificationStatus.NOT_VERIFIED.value
    assert verified.verification_record is not None
    assert verified.verification_record.identifier_results[0].format_valid is True
    assert verified.verification_record.identifier_results[0].existence_status == "NOT_FOUND"


def test_syntactically_valid_but_nonexistent_doi_is_blocked() -> None:
    result = outcome(IdentifierType.DOI, "10.1234/missing", ExistenceVerificationStatus.NOT_FOUND)

    verified = verify_publication_authoritatively(
        article(doi="10.1234/missing"),
        pubmed_connector=unused_pubmed(),
        crossref_connector=StubCrossref(result),
    )

    assert verified.verification_status == VerificationStatus.NOT_VERIFIED.value
    assert verified.verification_record.identifier_results[0].existence_status == "NOT_FOUND"


def test_existing_publication_with_reconciled_metadata_is_verified() -> None:
    pmid = outcome(
        IdentifierType.PMID,
        "12345678",
        ExistenceVerificationStatus.CONFIRMED,
        metadata=matching_metadata(pmid="12345678"),
        raw={"result": {"12345678": {"uid": "12345678"}}},
    )
    doi = outcome(
        IdentifierType.DOI,
        "10.1234/existing",
        ExistenceVerificationStatus.CONFIRMED,
        metadata=matching_metadata(doi="10.1234/existing"),
        raw={"message": {"DOI": "10.1234/existing"}},
    )

    verified = verify_publication_authoritatively(
        article(pmid="12345678", doi="10.1234/existing"),
        pubmed_connector=StubPubMed(pmid),
        crossref_connector=StubCrossref(doi),
    )

    record = verified.verification_record
    assert verified.verification_status == VerificationStatus.VERIFIED.value
    assert record is not None
    assert record.reconciliation_status == MetadataReconciliationStatus.MATCHED.value
    assert len(record.identifier_results) == 2
    assert {item.source_name for item in record.identifier_results} == {"NCBI PubMed", "Crossref"}
    assert all(item.checked_at == NOW for item in record.identifier_results)
    assert all(item.raw_outcome for item in record.identifier_results)
    assert verified.last_verified_at is not None


@pytest.mark.parametrize(
    ("identifier_field", "identifier_value"),
    [("pmid", "ABC123"), ("doi", "not-a-doi")],
)
def test_malformed_identifier_is_never_sent_to_authority(
    identifier_field: str, identifier_value: str
) -> None:
    verified = verify_publication_authoritatively(
        article(**{identifier_field: identifier_value}),
        pubmed_connector=unused_pubmed(),
        crossref_connector=unused_crossref(),
    )

    result = verified.verification_record.identifier_results[0]
    assert verified.verification_status == VerificationStatus.NOT_VERIFIED.value
    assert result.format_valid is False
    assert result.existence_status == ExistenceVerificationStatus.MALFORMED.value
    assert result.source_name == "local-format-validator"


def test_significant_metadata_conflict_prevents_verified() -> None:
    result = outcome(
        IdentifierType.PMID,
        "12345678",
        ExistenceVerificationStatus.CONFIRMED,
        metadata={**matching_metadata(pmid="12345678"), "title": "A different publication"},
    )

    verified = verify_publication_authoritatively(
        article(pmid="12345678"),
        pubmed_connector=StubPubMed(result),
        crossref_connector=unused_crossref(),
    )

    assert verified.verification_status == VerificationStatus.CONFLICTING_METADATA.value
    assert verified.verification_record.reconciliation_status == "CONFLICTING"
    assert verified.verification_record.metadata_conflicts == ("NCBI PubMed:title",)


@pytest.mark.parametrize(
    "external_status",
    [
        ExistenceVerificationStatus.SOURCE_UNAVAILABLE,
        ExistenceVerificationStatus.TIMEOUT,
        ExistenceVerificationStatus.INVALID_RESPONSE,
    ],
)
def test_external_failure_is_preserved_and_blocked(
    external_status: ExistenceVerificationStatus,
) -> None:
    result = outcome(
        IdentifierType.PMID,
        "12345678",
        external_status,
        raw={"failure": external_status.value},
    )

    verified = verify_publication_authoritatively(
        article(pmid="12345678"),
        pubmed_connector=StubPubMed(result),
        crossref_connector=unused_crossref(),
    )

    stored = verified.verification_record.identifier_results[0]
    assert verified.verification_status == VerificationStatus.NOT_VERIFIED.value
    assert stored.existence_status == external_status.value
    assert stored.raw_outcome == {"failure": external_status.value}
    assert stored.checked_at == NOW


def test_regex_only_attempt_cannot_promote_to_verified() -> None:
    locally_checked = verify_article_metadata(article(pmid="12345678", doi="10.1234/regex-only"))

    assert locally_checked.verification_status == VerificationStatus.PARTIALLY_VERIFIED.value
    assert locally_checked.verification_record is None
