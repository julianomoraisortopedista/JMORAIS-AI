from __future__ import annotations

from jmoraIs.scientific_domain import (
    ExistenceVerificationStatus,
    IdentifierType,
    IdentifierVerificationResult,
    MetadataReconciliationStatus,
    PublicationVerificationRecord,
    ScientificArticle,
    VerificationStatus,
)
from jmoraIs.verification import CitationVerificationGate
from jmoraIs.vancouver import render_vancouver


def test_verified_article_passes_gate() -> None:
    article = ScientificArticle(
        title="Evidence for early rehabilitation after knee surgery",
        authors=["Doe, Jane", "Smith, John"],
        journal="Orthopedic Review",
        publication_year=2024,
        verification_status=VerificationStatus.VERIFIED.value,
        verification_record=PublicationVerificationRecord(
            identifier_results=[
                IdentifierVerificationResult(
                    identifier_type=IdentifierType.PMID.value,
                    identifier_value="12345678",
                    format_valid=True,
                    existence_status=ExistenceVerificationStatus.CONFIRMED.value,
                    source_name="NCBI PubMed",
                    raw_outcome={"uid": "12345678"},
                )
            ],
            reconciliation_status=MetadataReconciliationStatus.MATCHED.value,
            final_status=VerificationStatus.VERIFIED.value,
            policy_version="ST-02",
            search_run_id="search-001",
        ),
    )

    assert CitationVerificationGate.evaluate(article) == VerificationStatus.VERIFIED
    assert CitationVerificationGate.can_render_trusted(article) is True
    assert "withheld" in render_vancouver(article).lower()


def test_forged_verified_status_without_authoritative_record_is_blocked() -> None:
    article = ScientificArticle(
        title="Evidence for early rehabilitation after knee surgery",
        authors=["Doe, Jane"],
        journal="Orthopedic Review",
        publication_year=2024,
        pmid="12345678",
        verification_status=VerificationStatus.VERIFIED.value,
    )

    assert CitationVerificationGate.evaluate(article) == VerificationStatus.NOT_VERIFIED
    assert "withheld" in render_vancouver(article).lower()


def test_partially_verified_article_is_blocked() -> None:
    article = ScientificArticle(
        title="Evidence for early rehabilitation after knee surgery",
        authors=["Doe, Jane"],
        journal="Orthopedic Review",
        publication_year=2024,
        verification_status=VerificationStatus.PARTIALLY_VERIFIED.value,
    )

    assert CitationVerificationGate.evaluate(article) == VerificationStatus.PARTIALLY_VERIFIED
    assert CitationVerificationGate.is_blocked(article) is True
    rendered = render_vancouver(article)
    assert "withheld" in rendered.lower()
    assert "PARTIALLY_VERIFIED" in rendered


def test_conflicting_metadata_article_is_blocked() -> None:
    article = ScientificArticle(
        title="Evidence for early rehabilitation after knee surgery",
        authors=["Doe, Jane"],
        journal="Orthopedic Review",
        publication_year=2024,
        verification_status=VerificationStatus.CONFLICTING_METADATA.value,
    )

    assert CitationVerificationGate.evaluate(article) == VerificationStatus.CONFLICTING_METADATA
    assert CitationVerificationGate.is_blocked(article) is True
    rendered = render_vancouver(article)
    assert "withheld" in rendered.lower()
    assert "CONFLICTING_METADATA" in rendered or "conflict" in rendered.lower()


def test_not_verified_article_is_blocked() -> None:
    article = ScientificArticle(
        title="Evidence for early rehabilitation after knee surgery",
        authors=["Doe, Jane"],
        journal="Orthopedic Review",
        publication_year=2024,
        verification_status=VerificationStatus.NOT_VERIFIED.value,
    )

    assert CitationVerificationGate.evaluate(article) == VerificationStatus.NOT_VERIFIED
    assert CitationVerificationGate.is_blocked(article) is True
    rendered = render_vancouver(article)
    assert "withheld" in rendered.lower()
    assert "NOT_VERIFIED" in rendered or "not verified" in rendered.lower()
