from datetime import date, datetime, timezone

import pytest

from jmoraIs.application import ScientificEvidencePackagePort
from jmoraIs.evidence_ledger import AppendOnlyEvidenceLedger, hash_payload
from jmoraIs.infrastructure import InMemoryPackageCatalogRepository
from jmoraIs.scientific_domain import (
    ExistenceVerificationStatus, IdentifierVerificationResult, MetadataReconciliationStatus,
    PublicationVerificationRecord, ScientificArticle, SourceProvenance, VerificationStatus,
)
from jmoraIs.vancouver import StrictVancouverFormatter, VancouverBlockedError, render_vancouver

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def article(**changes):
    values = dict(
        article_id="article-1", title="Verified study", authors=["Doe J", "Smith A"],
        journal="Medical Journal", publication_year=2025, pmid="12345678",
        publication_type="journal_article", verification_status="VERIFIED",
        provenance=SourceProvenance(source_id="prov-1", source_name="NCBI PubMed"),
        verification_record=PublicationVerificationRecord(
            identifier_results=[IdentifierVerificationResult(
                identifier_type="PMID", identifier_value="12345678", format_valid=True,
                existence_status=ExistenceVerificationStatus.CONFIRMED.value,
                source_name="NCBI PubMed", checked_at=NOW,
            )], reconciliation_status=MetadataReconciliationStatus.MATCHED.value,
            final_status="VERIFIED", policy_version="ST-02", search_run_id="search-1",
        ),
    )
    values.update(changes)
    return ScientificArticle(**values)


def formatter_for(record):
    ledger = AppendOnlyEvidenceLedger()
    claim = ledger.create_claim("Claim", claim_id="claim-1", created_at=NOW)
    _, support, _ = ledger.register_evidence(
        claim_id=claim.claim_id, source_name="NCBI PubMed", source_type="pubmed",
        passage="Exact result", pmid=record.pmid, doi=record.doi, pmcid=record.pmcid,
        payload_hash=hash_payload({"article": record.article_id}), retrieved_at=NOW,
        verification_version="ST-02", pipeline_version="ST-03", policy_version="ST-02",
        support_direction="supporting", occurred_at=NOW,
    )
    packages = ScientificEvidencePackagePort(catalog=InMemoryPackageCatalogRepository(), clock=lambda: NOW)
    package = packages.issue(
        article=record, ledger=ledger, claim_id=claim.claim_id,
        support_ids=(support.support_id,), pipeline_version="ST-04",
    )
    return StrictVancouverFormatter(packages, clock=lambda: NOW), package.package_id


def test_valid_verified_journal_article_and_formatter_version():
    record = article(volume="12", issue="3", pages="10-18", doi=None)
    formatter, package_id = formatter_for(record)
    result = formatter.render(package_id=package_id, article=record)
    assert result.rendered_text == "Doe J, Smith A. Verified study. Medical Journal. 2025;12(3):10-18."
    assert result.formatter_version == StrictVancouverFormatter.FORMATTER_VERSION


@pytest.mark.parametrize("status", ["PARTIALLY_VERIFIED", "CONFLICTING_METADATA", "NOT_VERIFIED"])
def test_every_non_verified_status_is_blocked(status):
    record = article(verification_status=status)
    assert "withheld" in render_vancouver(record).lower()


def test_incomplete_metadata_is_blocked_without_invention():
    record = article(journal=None)
    formatter, package_id = formatter_for(record)
    with pytest.raises(VancouverBlockedError, match="journal"):
        formatter.render(package_id=package_id, article=record)


def test_missing_doi_is_legitimately_allowed():
    record = article(doi=None)
    formatter, package_id = formatter_for(record)
    rendered = formatter.render(package_id=package_id, article=record).rendered_text
    assert "doi:" not in rendered
    assert "Unavailable" not in rendered


def test_multiple_authors_use_vancouver_six_author_limit():
    record = article(authors=[f"Author {number}" for number in range(1, 8)])
    formatter, package_id = formatter_for(record)
    rendered = formatter.render(package_id=package_id, article=record).rendered_text
    assert "Author 6 et al" in rendered
    assert "Author 7" not in rendered


def test_electronic_article_requires_and_formats_access_information():
    record = article(
        publication_type="electronic_article", url="https://example.org/article",
        accessed_at=date(2026, 1, 1),
    )
    formatter, package_id = formatter_for(record)
    rendered = formatter.render(package_id=package_id, article=record).rendered_text
    assert "[Internet]" in rendered
    assert "[cited 2026-01-01]" in rendered
    assert "Available from: https://example.org/article" in rendered


def test_model_generated_text_cannot_be_formatted_directly():
    record = article()
    formatter, package_id = formatter_for(record)
    with pytest.raises(VancouverBlockedError, match="model text"):
        formatter.render(package_id=package_id, article="Doe J. Invented citation. Journal. 2025.")
    assert "withheld" in render_vancouver("Doe J. Invented citation. Journal. 2025.").lower()


def test_metadata_changed_after_package_emission_is_blocked():
    record = article()
    formatter, package_id = formatter_for(record)
    record.title = "Model-invented replacement title"
    with pytest.raises(VancouverBlockedError, match="differs"):
        formatter.render(package_id=package_id, article=record)


@pytest.mark.parametrize("publication_type", ["guideline", "book", "book_chapter"])
def test_future_publication_types_have_strict_field_validation(publication_type):
    record = article(publication_type=publication_type)
    formatter, package_id = formatter_for(record)
    with pytest.raises(VancouverBlockedError, match="missing required metadata"):
        formatter.render(package_id=package_id, article=record)
