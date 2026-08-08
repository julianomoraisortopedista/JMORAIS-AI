from __future__ import annotations

import re
from collections import OrderedDict
from typing import Any, Optional

from jmoraIs.scientific_domain import (
    ArticleRecord,
    EvidenceLedgerEntry as LedgerEntry,
    ScientificArticle,
    SourceProvenance,
    SupportDirection,
    VerificationStatus,
)

DOI_PATTERN = re.compile(r"^10\.\d{4,9}/\S+$")
PMID_PATTERN = re.compile(r"^\d{1,8}$")
PMCID_PATTERN = re.compile(r"^PMC\d+$", re.IGNORECASE)


def _normalize_identifier(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return str(int(value))
    return str(value).strip() or None


def normalize_title(value: Any) -> str:
    text = (value or "").strip()
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def normalize_pmid(value: Any) -> Optional[str]:
    identifier = _normalize_identifier(value)
    if identifier is None:
        return None
    return identifier if PMID_PATTERN.fullmatch(identifier) else None


def normalize_pmcid(value: Any) -> Optional[str]:
    identifier = _normalize_identifier(value)
    if identifier is None:
        return None
    cleaned = identifier.strip()
    if PMCID_PATTERN.fullmatch(cleaned):
        return cleaned.upper()
    return None


def normalize_doi(value: Any) -> Optional[str]:
    identifier = _normalize_identifier(value)
    if identifier is None:
        return None
    candidate = identifier.strip().strip(".;()[]{}")
    candidate = candidate.replace("https://doi.org/", "").replace("http://dx.doi.org/", "")
    candidate = candidate.replace("doi:", "", 1).strip()
    if candidate.startswith("DOI:"):
        candidate = candidate[4:].strip()
    if DOI_PATTERN.fullmatch(candidate):
        return candidate
    if candidate.startswith("10.") and "/" in candidate:
        return candidate
    return None


def validate_pmid(value: Any) -> bool:
    return normalize_pmid(value) is not None


def validate_doi(value: Any) -> bool:
    return normalize_doi(value) is not None


def normalize_article(raw: dict[str, Any]) -> ArticleRecord:
    title = (raw.get("title") or "").strip()
    journal = (raw.get("journal") or raw.get("source_journal") or "").strip() or None
    year_value = raw.get("year")
    year = int(year_value) if isinstance(year_value, int) else None
    if isinstance(year_value, str) and year_value.isdigit():
        year = int(year_value)
    authors_value = raw.get("authors") or []
    if isinstance(authors_value, str):
        authors = [author.strip() for author in authors_value.split(",") if author.strip()]
    elif isinstance(authors_value, list):
        authors = [str(author).strip() for author in authors_value if str(author).strip()]
    else:
        authors = []

    article = ScientificArticle(
        title=title,
        journal=journal,
        year=year,
        pmid=normalize_pmid(raw.get("pmid") or raw.get("pmid_value")),
        doi=normalize_doi(raw.get("doi") or raw.get("doi_value") or raw.get("identifier")),
        pmcid=normalize_pmcid(raw.get("pmcid") or raw.get("pmcid_value")),
        abstract=(raw.get("abstract") or "").strip() or None,
        authors=authors,
        source_type=(raw.get("source") or raw.get("source_type") or "pubmed").strip() or "pubmed",
        source_locator=(raw.get("source_locator") or "").strip() or None,
        normalized_title=normalize_title(title),
        raw_metadata=raw,
        provenance=SourceProvenance(
            source_type=(raw.get("source") or raw.get("source_type") or "pubmed").strip() or "pubmed",
            source_name=(raw.get("source") or raw.get("source_type") or "pubmed").strip() or "pubmed",
            source_locator=(raw.get("source_locator") or "").strip() or None,
            raw_payload=raw,
        ),
    )
    if article.pmid and article.doi is None and isinstance(raw.get("elocationid"), str):
        article.doi = normalize_doi(raw.get("elocationid"))
    return article


def _metadata_is_present(article: ArticleRecord) -> bool:
    return bool(article.title and (article.journal or article.year or article.authors))


def reconcile_with_crossref(article: ArticleRecord, crossref_record: dict[str, Any] | None) -> ArticleRecord:
    if not crossref_record:
        return article

    crossref_title = (crossref_record.get("title") or "").strip()
    crossref_journal = (crossref_record.get("journal") or "").strip() or None
    crossref_year = crossref_record.get("year")
    if isinstance(crossref_year, str) and crossref_year.isdigit():
        crossref_year = int(crossref_year)
    crossref_authors = crossref_record.get("authors") or []
    if isinstance(crossref_authors, str):
        crossref_authors = [author.strip() for author in crossref_authors.split(",") if author.strip()]
    elif not isinstance(crossref_authors, list):
        crossref_authors = []

    conflicts: list[str] = []
    if article.title and crossref_title and normalize_title(article.title) != normalize_title(crossref_title):
        conflicts.append("title")
    if article.journal and crossref_journal and normalize_title(article.journal) != normalize_title(crossref_journal):
        conflicts.append("journal")
    if article.year and crossref_year and article.year != crossref_year:
        conflicts.append("year")
    if article.authors and crossref_authors:
        def author_key(authors: list[str]) -> tuple[tuple[str, ...], ...]:
            normalized_authors = []
            for author in authors:
                cleaned = re.sub(r"[^a-z0-9]+", " ", author.lower()).strip()
                tokens = tuple(sorted(token for token in cleaned.split() if token))
                if tokens:
                    normalized_authors.append(tokens)
            return tuple(sorted(normalized_authors))

        if author_key(article.authors) != author_key(crossref_authors):
            conflicts.append("authors")

    if conflicts:
        article.verification_status = VerificationStatus.CONFLICTING_METADATA.value
        article.raw_metadata = {**(article.raw_metadata or {}), "crossref_conflicts": conflicts, "crossref_record": crossref_record}
        return article

    if article.title and (article.doi or article.pmid or article.pmcid):
        article.verification_status = VerificationStatus.VERIFIED.value
    elif _metadata_is_present(article):
        article.verification_status = VerificationStatus.PARTIALLY_VERIFIED.value
    return article


def verify_article_metadata(article: ArticleRecord, crossref_record: dict[str, Any] | None = None) -> ArticleRecord:
    if not article.title:
        article.verification_status = VerificationStatus.NOT_VERIFIED.value
        return article

    if article.pmid and not validate_pmid(article.pmid):
        article.pmid = None
    if article.doi and not validate_doi(article.doi):
        article.doi = None
    if article.pmcid and not normalize_pmcid(article.pmcid):
        article.pmcid = None

    if crossref_record is not None:
        article = reconcile_with_crossref(article, crossref_record)
        if article.verification_status == VerificationStatus.CONFLICTING_METADATA.value:
            return article

    verified_identifier = bool(article.pmid and validate_pmid(article.pmid)) or bool(article.doi and validate_doi(article.doi))
    if verified_identifier and _metadata_is_present(article):
        article.verification_status = VerificationStatus.VERIFIED.value
    elif verified_identifier or _metadata_is_present(article):
        article.verification_status = VerificationStatus.PARTIALLY_VERIFIED.value
    else:
        article.verification_status = VerificationStatus.NOT_VERIFIED.value

    return article


def deduplication_key(article: ArticleRecord) -> tuple[str, str]:
    if article.doi:
        return ("doi", article.doi)
    if article.pmid:
        return ("pmid", article.pmid)
    if article.pmcid:
        return ("pmcid", article.pmcid)
    normalized_title = normalize_title(article.title)
    if normalized_title:
        return ("normalized_title", normalized_title)
    author_key = "|".join(sorted(normalize_title(author) for author in article.authors if author))
    year_key = str(article.year or "")
    journal_key = normalize_title(article.journal or "")
    return ("author_year_journal", f"{author_key}|{year_key}|{journal_key}")


def deduplicate_articles(articles: list[ArticleRecord]) -> tuple[list[ArticleRecord], list[dict[str, Any]]]:
    selected: OrderedDict[str, ArticleRecord] = OrderedDict()
    merge_decisions: list[dict[str, Any]] = []

    for article in articles:
        key = "|".join(deduplication_key(article))
        if key not in selected:
            selected[key] = article
            continue

        existing = selected[key]
        kept = article if article.verification_status == VerificationStatus.VERIFIED.value and existing.verification_status != VerificationStatus.VERIFIED.value else existing
        merge_decisions.append(
            {
                "key": key,
                "kept_article_id": kept.article_id,
                "dropped_article_id": article.article_id,
                "reason": "duplicate_by_priority",
                "conflicting_values": {
                    "pmid": [existing.pmid, article.pmid],
                    "doi": [existing.doi, article.doi],
                    "title": [existing.title, article.title],
                },
            }
        )
        selected[key] = kept

    return list(selected.values()), merge_decisions


def build_ledger_entry(
    *,
    claim_id: str,
    claim_text: str,
    source_id: int | str,
    source_type: str,
    source_locator: Optional[str],
    supporting_passage: Optional[str],
    article: ArticleRecord,
    support_direction: str = SupportDirection.SUPPORTING.value,
    confidence: float = 0.9,
    limitations: Optional[str] = None,
) -> LedgerEntry:
    return LedgerEntry(
        claim_id=claim_id,
        claim_text=claim_text,
        source_id=source_id,
        source_type=source_type,
        source_locator=source_locator,
        supporting_passage=supporting_passage,
        pmid=article.pmid,
        doi=article.doi,
        pmcid=article.pmcid,
        support_direction=support_direction,
        verification_status=article.verification_status,
        confidence=confidence,
        limitations=limitations,
    )


__all__ = [
    "ArticleRecord",
    "LedgerEntry",
    "ScientificArticle",
    "SourceProvenance",
    "VerificationStatus",
    "SupportDirection",
    "normalize_article",
    "normalize_doi",
    "normalize_pmid",
    "normalize_pmcid",
    "validate_doi",
    "validate_pmid",
    "verify_article_metadata",
    "reconcile_with_crossref",
    "deduplicate_articles",
    "build_ledger_entry",
]
