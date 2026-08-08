from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


DOI_PATTERN = re.compile(r"^10\.\d{4,9}/\S+$")
PMID_PATTERN = re.compile(r"^\d{1,8}$")


@dataclass
class ArticleRecord:
    title: str
    authors: list[str] = field(default_factory=list)
    journal: Optional[str] = None
    year: Optional[int] = None
    pmid: Optional[str] = None
    doi: Optional[str] = None
    abstract: Optional[str] = None
    source: str = "pubmed"
    source_locator: Optional[str] = None
    verification_status: str = "NOT_VERIFIED"


@dataclass
class LedgerEntry:
    claim_id: str
    claim_text: str
    source_id: int
    source_type: str
    source_locator: Optional[str]
    supporting_passage: Optional[str]
    pmid: Optional[str]
    doi: Optional[str]
    verification_status: str
    support_direction: str = "supporting"
    confidence: float = 0.0
    limitations: Optional[str] = None
    verified_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def _normalize_identifier(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return str(int(value))
    return str(value).strip() or None


def normalize_article(raw: dict[str, Any]) -> ArticleRecord:
    article = ArticleRecord(
        title=(raw.get("title") or "").strip(),
        journal=(raw.get("journal") or "").strip() or None,
        year=int(raw["year"]) if raw.get("year") and str(raw.get("year")).isdigit() else None,
        pmid=_normalize_identifier(raw.get("pmid")),
        doi=_normalize_identifier(raw.get("doi")),
        abstract=(raw.get("abstract") or "").strip() or None,
        source=(raw.get("source") or "pubmed").strip() or "pubmed",
        source_locator=(raw.get("source_locator") or "").strip() or None,
    )
    authors = raw.get("authors") or []
    if isinstance(authors, str):
        article.authors = [author.strip() for author in authors.split(",") if author.strip()]
    else:
        article.authors = [str(author).strip() for author in authors if str(author).strip()]
    return article


def verify_article_metadata(article: ArticleRecord) -> ArticleRecord:
    if not article.title:
        article.verification_status = "NOT_VERIFIED"
        return article

    has_pmid = bool(article.pmid and PMID_PATTERN.fullmatch(article.pmid))
    has_doi = bool(article.doi and DOI_PATTERN.fullmatch(article.doi))

    if has_pmid or has_doi:
        article.verification_status = "VERIFIED"
    elif article.journal or article.authors:
        article.verification_status = "PARTIALLY_VERIFIED"
    else:
        article.verification_status = "NOT_VERIFIED"
    return article


def build_ledger_entry(
    *,
    claim_id: str,
    claim_text: str,
    source_id: int,
    source_type: str,
    source_locator: Optional[str],
    supporting_passage: Optional[str],
    article: ArticleRecord,
    support_direction: str = "supporting",
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
        verification_status=article.verification_status,
        support_direction=support_direction,
        confidence=confidence,
        limitations=limitations,
    )
