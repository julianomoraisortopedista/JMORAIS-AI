from __future__ import annotations

import re
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Optional

from jmoraIs.scientific_domain import (
    ArticleRecord,
    EvidenceLedgerEntry as LedgerEntry,
    ExistenceVerificationStatus,
    IdentifierType,
    IdentifierVerificationResult,
    MetadataReconciliationStatus,
    PublicationStatus,
    PublicationVerificationRecord,
    ScientificArticle,
    SourceProvenance,
    SupportDirection,
    VerificationStatus,
)

DOI_PATTERN = re.compile(r"^10\.\d{4,9}/\S+$")
PMID_PATTERN = re.compile(r"^\d{1,8}$")
PMCID_PATTERN = re.compile(r"^PMC\d+$", re.IGNORECASE)


class CitationVerificationGate:
    @staticmethod
    def evaluate(article: ArticleRecord) -> VerificationStatus:
        raw_status = getattr(article, "verification_status", VerificationStatus.NOT_VERIFIED.value)
        if raw_status is None:
            return VerificationStatus.NOT_VERIFIED
        status = str(raw_status)
        if hasattr(raw_status, "value"):
            status = str(raw_status.value)
        status = status.upper()

        if status == VerificationStatus.VERIFIED.value:
            record = getattr(article, "verification_record", None)
            if record is None or record.final_status != VerificationStatus.VERIFIED.value:
                return VerificationStatus.NOT_VERIFIED
            if record.reconciliation_status != MetadataReconciliationStatus.MATCHED.value:
                return VerificationStatus.NOT_VERIFIED
            if record.policy_version != "ST-02" or not record.search_run_id:
                return VerificationStatus.NOT_VERIFIED
            if not record.identifier_results or not all(
                result.existence_confirmed for result in record.identifier_results
            ):
                return VerificationStatus.NOT_VERIFIED
            return VerificationStatus.VERIFIED
        if status == VerificationStatus.PARTIALLY_VERIFIED.value:
            return VerificationStatus.PARTIALLY_VERIFIED
        if status == VerificationStatus.CONFLICTING_METADATA.value:
            return VerificationStatus.CONFLICTING_METADATA
        if status == VerificationStatus.NOT_VERIFIED.value:
            return VerificationStatus.NOT_VERIFIED
        return VerificationStatus.NOT_VERIFIED

    @staticmethod
    def can_render_trusted(article: ArticleRecord) -> bool:
        return CitationVerificationGate.evaluate(article) == VerificationStatus.VERIFIED

    @staticmethod
    def warning_for(article: ArticleRecord) -> Optional[str]:
        status = CitationVerificationGate.evaluate(article)
        if status == VerificationStatus.PARTIALLY_VERIFIED:
            return "Visible warning: article metadata is only partially verified."
        if status == VerificationStatus.CONFLICTING_METADATA:
            return "Visible warning: metadata conflict detected; citation is not trusted."
        if status == VerificationStatus.NOT_VERIFIED:
            return "Visible warning: citation is not verified and cannot be trusted."
        return None

    @staticmethod
    def is_blocked(article: ArticleRecord) -> bool:
        return CitationVerificationGate.evaluate(article) != VerificationStatus.VERIFIED


def verify_citation(article: ArticleRecord) -> VerificationStatus:
    return CitationVerificationGate.evaluate(article)


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
        article.verification_status = VerificationStatus.PARTIALLY_VERIFIED.value
    elif _metadata_is_present(article):
        article.verification_status = VerificationStatus.PARTIALLY_VERIFIED.value
    return article


def verify_article_metadata(article: ArticleRecord, crossref_record: dict[str, Any] | None = None) -> ArticleRecord:
    """Perform local format checks only; never assert authoritative existence.

    Kept as a compatibility entry point for normalization callers. Authoritative
    verification requires ``verify_publication_authoritatively`` with explicit
    NCBI/Crossref connectors.
    """
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

    format_valid_identifier = bool(article.pmid and validate_pmid(article.pmid)) or bool(article.doi and validate_doi(article.doi))
    if format_valid_identifier or _metadata_is_present(article):
        article.verification_status = VerificationStatus.PARTIALLY_VERIFIED.value
    else:
        article.verification_status = VerificationStatus.NOT_VERIFIED.value

    return article


def _malformed_result(identifier_type: IdentifierType, value: str) -> IdentifierVerificationResult:
    return IdentifierVerificationResult(
        identifier_type=identifier_type.value,
        identifier_value=value,
        format_valid=False,
        existence_status=ExistenceVerificationStatus.MALFORMED.value,
        source_name="local-format-validator",
        checked_at=datetime.now(timezone.utc),
        raw_outcome={"format_valid": False},
        error_code=ExistenceVerificationStatus.MALFORMED.value,
    )


def _author_key(authors: list[str]) -> tuple[tuple[str, ...], ...]:
    normalized_authors = []
    for author in authors:
        cleaned = re.sub(r"[^a-z0-9]+", " ", author.lower()).strip()
        tokens = tuple(sorted(token for token in cleaned.split() if token))
        if tokens:
            normalized_authors.append(tokens)
    return tuple(sorted(normalized_authors))


def _reconcile_metadata_fields(
    article: ArticleRecord, metadata: dict[str, Any]
) -> tuple[list[str], list[str], list[str]]:
    conflicts: list[str] = []
    matches: list[str] = []
    missing: list[str] = []
    authoritative_title = metadata.get("title")
    authoritative_journal = metadata.get("journal")
    authoritative_year = metadata.get("year")
    authoritative_authors = metadata.get("authors") or []

    comparisons = {
        "title": (
            article.title,
            authoritative_title,
            lambda left, right: normalize_title(left) == normalize_title(right),
        ),
        "journal": (
            article.journal,
            authoritative_journal,
            lambda left, right: normalize_title(left) == normalize_title(right),
        ),
        "year": (article.publication_year, authoritative_year, lambda left, right: left == right),
        "authors": (article.authors, authoritative_authors, lambda left, right: _author_key(left) == _author_key(right)),
    }
    for field_name, (local_value, authoritative_value, comparator) in comparisons.items():
        if not local_value or not authoritative_value:
            missing.append(field_name)
        elif comparator(local_value, authoritative_value):
            matches.append(field_name)
        else:
            conflicts.append(field_name)

    for field_name, local_value in (("pmid", article.pmid), ("doi", article.doi)):
        authoritative_value = metadata.get(field_name)
        if not local_value or not authoritative_value:
            continue
        if field_name == "doi":
            equal = local_value.lower() == str(authoritative_value).lower()
        else:
            equal = local_value == str(authoritative_value)
        (matches if equal else conflicts).append(field_name)
    return conflicts, matches, missing


def decide_publication_verification(
    article: ArticleRecord,
    identifier_results: list[IdentifierVerificationResult],
    *,
    checked_at: datetime | None = None,
    policy_version: str = "ST-02",
    search_run_id: str | None = None,
) -> ArticleRecord:
    """Reconcile authoritative outcomes and make the sole final status decision."""
    decision_time = checked_at or datetime.now(timezone.utc)
    conflicts: list[str] = []
    matches: list[str] = []
    missing: list[str] = []

    for result in identifier_results:
        if not result.existence_confirmed or not result.authoritative_metadata:
            continue
        identifier_field = result.identifier_type.lower()
        authoritative_identifier = result.authoritative_metadata.get(identifier_field)
        if authoritative_identifier and (
            str(authoritative_identifier).lower() != result.identifier_value.lower()
        ):
            conflicts.append(f"{result.source_name}:{identifier_field}")
        result_conflicts, result_matches, result_missing = _reconcile_metadata_fields(
            article, result.authoritative_metadata
        )
        for field_name in result_conflicts:
            conflicts.append(f"{result.source_name}:{field_name}")
        for field_name in result_matches:
            matches.append(f"{result.source_name}:{field_name}")
        for field_name in result_missing:
            missing.append(f"{result.source_name}:{field_name}")

    confirmed = [result for result in identifier_results if result.existence_confirmed]
    all_confirmed = bool(identifier_results) and len(confirmed) == len(identifier_results)

    if conflicts:
        reconciliation_status = MetadataReconciliationStatus.CONFLICTING
        final_status = VerificationStatus.CONFLICTING_METADATA
    elif not all_confirmed:
        reconciliation_status = MetadataReconciliationStatus.NOT_PERFORMED
        final_status = VerificationStatus.NOT_VERIFIED
    elif missing:
        reconciliation_status = MetadataReconciliationStatus.PARTIAL_MATCH
        final_status = VerificationStatus.PARTIALLY_VERIFIED
    elif not any(match.endswith(":title") for match in matches):
        reconciliation_status = MetadataReconciliationStatus.INSUFFICIENT_METADATA
        final_status = VerificationStatus.PARTIALLY_VERIFIED
    else:
        reconciliation_status = MetadataReconciliationStatus.MATCHED
        final_status = VerificationStatus.VERIFIED

    record = PublicationVerificationRecord(
        identifier_results=list(identifier_results),
        reconciliation_status=reconciliation_status.value,
        metadata_conflicts=list(dict.fromkeys(conflicts)),
        metadata_matches=list(dict.fromkeys(matches)),
        metadata_missing=list(dict.fromkeys(missing)),
        final_status=final_status.value,
        checked_at=decision_time,
        policy_version=policy_version,
        search_run_id=search_run_id,
    )
    article.verification_record = record
    article.verification_status = final_status.value
    article.last_verified_at = decision_time
    return article


def verify_publication_authoritatively(
    article: ArticleRecord,
    *,
    pubmed_connector: Any,
    crossref_connector: Any,
) -> ArticleRecord:
    """Verify existence, reconcile metadata, then assign the final status.

    No connector result is used to fill missing article metadata. The raw
    authoritative outcomes remain attached to ``verification_record``.
    """
    checked_at = datetime.now(timezone.utc)
    results: list[IdentifierVerificationResult] = []

    raw_pmid = _normalize_identifier(article.pmid)
    raw_doi = _normalize_identifier(article.doi)

    if raw_pmid:
        normalized_pmid = normalize_pmid(raw_pmid)
        if normalized_pmid is None:
            results.append(_malformed_result(IdentifierType.PMID, raw_pmid))
        else:
            results.append(pubmed_connector.search_by_pmid(normalized_pmid))

    if raw_doi:
        normalized_doi = normalize_doi(raw_doi)
        if normalized_doi is None:
            results.append(_malformed_result(IdentifierType.DOI, raw_doi))
        else:
            results.append(crossref_connector.search_by_doi(normalized_doi))

    return decide_publication_verification(article, results, checked_at=checked_at, policy_version="ST-01")


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
        duplicate = existing if kept is article else article
        merge_decisions.append(
            {
                "key": key,
                "kept_article_id": kept.article_id,
                "dropped_article_id": duplicate.article_id,
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
    search_run_id: Optional[str] = None,
    verified_at: Optional[Any] = None,
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
        search_run_id=search_run_id,
        verified_at=verified_at or datetime.now(timezone.utc),
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
    "verify_publication_authoritatively",
    "decide_publication_verification",
    "reconcile_with_crossref",
    "deduplicate_articles",
    "build_ledger_entry",
]
