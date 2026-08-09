from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4


class VerificationStatus(str, Enum):
    VERIFIED = "VERIFIED"
    PARTIALLY_VERIFIED = "PARTIALLY_VERIFIED"
    CONFLICTING_METADATA = "CONFLICTING_METADATA"
    NOT_VERIFIED = "NOT_VERIFIED"


class SupportDirection(str, Enum):
    SUPPORTING = "SUPPORTING"
    OPPOSING = "OPPOSING"
    NEUTRAL = "NEUTRAL"
    INCONCLUSIVE = "INCONCLUSIVE"


class PublicationStatus(str, Enum):
    RELIABLE = "RELIABLE"
    CORRECTED = "CORRECTED"
    RETRACTED = "RETRACTED"
    EXPRESSION_OF_CONCERN = "EXPRESSION_OF_CONCERN"
    UNKNOWN = "UNKNOWN"


class HumanReviewStage(str, Enum):
    DRAFT = "DRAFT"
    AI_REVIEWED = "AI_REVIEWED"
    PHYSICIAN_REVIEWED = "PHYSICIAN_REVIEWED"
    FINAL = "FINAL"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Journal:
    journal_id: str = field(default_factory=lambda: uuid4().hex)
    title: str = ""
    abbreviation: Optional[str] = None
    issn: Optional[str] = None
    country: Optional[str] = None


@dataclass
class Author:
    author_id: str = field(default_factory=lambda: uuid4().hex)
    name: str = ""
    orcid: Optional[str] = None
    affiliation: Optional[str] = None


@dataclass
class ArticleAuthor:
    article_id: str = ""
    author_id: str = ""
    author_order: int = 0
    is_corresponding: bool = False


@dataclass
class SourceProvenance:
    source_id: str = field(default_factory=lambda: uuid4().hex)
    source_type: str = "pubmed"
    source_database: str = "pubmed"
    source_name: str = ""
    source_locator: Optional[str] = None
    retrieved_at: datetime = field(default_factory=utc_now)
    record_hash: Optional[str] = None
    raw_payload: Optional[dict[str, Any]] = None


@dataclass
class ScientificArticle:
    internal_id: str = field(default_factory=lambda: uuid4().hex)
    article_id: str = field(default_factory=lambda: uuid4().hex)
    title: str = ""
    normalized_title: Optional[str] = None
    abstract: Optional[str] = None
    journal: Optional[str] = None
    journal_abbreviation: Optional[str] = None
    publication_year: Optional[int] = None
    year: Optional[int] = None
    publication_date: Optional[date] = None
    volume: Optional[str] = None
    issue: Optional[str] = None
    pages: Optional[str] = None
    doi: Optional[str] = None
    pmid: Optional[str] = None
    pmcid: Optional[str] = None
    issn: Optional[str] = None
    source_database: str = "pubmed"
    source_type: str = "pubmed"
    publication_type: Optional[str] = None
    study_design: Optional[str] = None
    language: Optional[str] = None
    keywords: list[str] = field(default_factory=list)
    authors: list[str] = field(default_factory=list)
    source_locator: Optional[str] = None
    verification_status: str = VerificationStatus.NOT_VERIFIED.value
    publication_status: str = PublicationStatus.UNKNOWN.value
    support_direction: str = SupportDirection.SUPPORTING.value
    provenance: Optional[SourceProvenance] = None
    human_review_status: str = HumanReviewStage.DRAFT.value
    raw_metadata: Optional[dict[str, Any]] = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    last_verified_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        if self.publication_year is None and self.year is not None:
            self.publication_year = self.year
        elif self.year is None and self.publication_year is not None:
            self.year = self.publication_year
        elif self.publication_year is not None and self.year is not None and self.publication_year != self.year:
            self.year = self.publication_year


@dataclass
class Citation:
    citation_id: str = field(default_factory=lambda: uuid4().hex)
    article_id: str = ""
    source_type: str = "scientific_article"
    rendered_vancouver: Optional[str] = None
    verification_status: str = VerificationStatus.NOT_VERIFIED.value
    source_locator: Optional[str] = None
    citation_warning: Optional[str] = None


@dataclass
class EvidenceClaim:
    claim_id: str = field(default_factory=lambda: uuid4().hex)
    claim_text: str = ""
    support_direction: str = SupportDirection.SUPPORTING.value
    verification_status: str = VerificationStatus.NOT_VERIFIED.value
    confidence: float = 0.0
    limitations: Optional[str] = None
    provenance: Optional[SourceProvenance] = None


@dataclass
class EvidenceLedgerEntry:
    claim_id: str = ""
    claim_text: str = ""
    source_id: str | int = ""
    source_type: str = "scientific_article"
    source_locator: Optional[str] = None
    pmid: Optional[str] = None
    doi: Optional[str] = None
    pmcid: Optional[str] = None
    support_direction: str = SupportDirection.SUPPORTING.value
    verification_status: str = VerificationStatus.NOT_VERIFIED.value
    confidence: float = 0.0
    limitations: Optional[str] = None
    verified_at: datetime = field(default_factory=utc_now)
    search_run_id: Optional[str] = None
    supporting_passage: Optional[str] = None


@dataclass
class SearchRun:
    search_id: str = field(default_factory=lambda: uuid4().hex)
    query: str = ""
    source: str = "pubmed"
    result_count: int = 0
    retrieved_at: datetime = field(default_factory=utc_now)
    status: str = "completed"


@dataclass
class VerificationRun:
    verification_id: str = field(default_factory=lambda: uuid4().hex)
    article_id: str = ""
    source_type: str = "pubmed"
    checks: list[str] = field(default_factory=list)
    overall_status: str = VerificationStatus.NOT_VERIFIED.value
    notes: Optional[str] = None
    run_at: datetime = field(default_factory=utc_now)


ArticleRecord = ScientificArticle
LedgerEntry = EvidenceLedgerEntry
