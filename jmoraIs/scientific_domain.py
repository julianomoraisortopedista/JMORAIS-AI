from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Mapping, Optional
from types import MappingProxyType
from uuid import uuid4


class VerificationStatus(str, Enum):
    VERIFIED = "VERIFIED"
    PARTIALLY_VERIFIED = "PARTIALLY_VERIFIED"
    CONFLICTING_METADATA = "CONFLICTING_METADATA"
    NOT_VERIFIED = "NOT_VERIFIED"


class IdentifierType(str, Enum):
    PMID = "PMID"
    DOI = "DOI"


class ExistenceVerificationStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    NOT_FOUND = "NOT_FOUND"
    MALFORMED = "MALFORMED"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    TIMEOUT = "TIMEOUT"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    NOT_CHECKED = "NOT_CHECKED"


class MetadataReconciliationStatus(str, Enum):
    MATCHED = "MATCHED"
    PARTIAL_MATCH = "PARTIAL_MATCH"
    CONFLICTING = "CONFLICTING"
    INSUFFICIENT_METADATA = "INSUFFICIENT_METADATA"
    NOT_PERFORMED = "NOT_PERFORMED"


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


@dataclass(frozen=True)
class Journal:
    journal_id: str = field(default_factory=lambda: uuid4().hex)
    title: str = ""
    abbreviation: Optional[str] = None
    issn: Optional[str] = None
    country: Optional[str] = None


@dataclass(frozen=True)
class Author:
    author_id: str = field(default_factory=lambda: uuid4().hex)
    name: str = ""
    orcid: Optional[str] = None
    affiliation: Optional[str] = None


@dataclass(frozen=True)
class ArticleAuthor:
    article_id: str = ""
    author_id: str = ""
    author_order: int = 0
    is_corresponding: bool = False


@dataclass(frozen=True)
class SourceProvenance:
    source_id: str = field(default_factory=lambda: uuid4().hex)
    source_type: str = "pubmed"
    source_database: str = "pubmed"
    source_name: str = ""
    source_locator: Optional[str] = None
    retrieved_at: datetime = field(default_factory=utc_now)
    record_hash: Optional[str] = None
    raw_payload: Optional[dict[str, Any]] = None

    def __post_init__(self) -> None:
        if isinstance(self.raw_payload, dict):
            object.__setattr__(self, "raw_payload", MappingProxyType(dict(self.raw_payload)))


@dataclass(frozen=True)
class IdentifierVerificationResult:
    identifier_type: str
    identifier_value: str
    format_valid: bool
    existence_status: str = ExistenceVerificationStatus.NOT_CHECKED.value
    source_name: str = ""
    source_locator: Optional[str] = None
    checked_at: datetime = field(default_factory=utc_now)
    raw_outcome: Any = None
    authoritative_metadata: Optional[dict[str, Any]] = None
    error_code: Optional[str] = None

    def __post_init__(self) -> None:
        if isinstance(self.raw_outcome, dict):
            object.__setattr__(self, "raw_outcome", MappingProxyType(dict(self.raw_outcome)))
        if isinstance(self.authoritative_metadata, dict):
            object.__setattr__(
                self, "authoritative_metadata", MappingProxyType(dict(self.authoritative_metadata)),
            )

    @property
    def existence_confirmed(self) -> bool:
        return (
            self.format_valid
            and self.existence_status == ExistenceVerificationStatus.CONFIRMED.value
        )


@dataclass(frozen=True)
class PublicationVerificationRecord:
    identifier_results: tuple[IdentifierVerificationResult, ...] = ()
    reconciliation_status: str = MetadataReconciliationStatus.NOT_PERFORMED.value
    metadata_conflicts: tuple[str, ...] = ()
    metadata_matches: tuple[str, ...] = ()
    metadata_missing: tuple[str, ...] = ()
    final_status: str = VerificationStatus.NOT_VERIFIED.value
    checked_at: datetime = field(default_factory=utc_now)
    policy_version: str = "ST-01"
    search_run_id: Optional[str] = None

    def __post_init__(self) -> None:
        for name in ("identifier_results", "metadata_conflicts", "metadata_matches", "metadata_missing"):
            object.__setattr__(self, name, tuple(getattr(self, name)))


@dataclass(frozen=True)
class DeduplicationDecision:
    deduplication_key: str
    kept_article_id: str
    duplicate_article_id: str
    reason: str
    conflicting_values: Mapping[str, tuple[Optional[str], ...]] = field(default_factory=dict)
    kept_provenance_id: Optional[str] = None
    duplicate_provenance_id: Optional[str] = None
    decided_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "conflicting_values",
            MappingProxyType({key: tuple(values) for key, values in self.conflicting_values.items()}),
        )


@dataclass(frozen=True)
class EligibleEvidenceResult:
    search_run: SearchRun
    articles: tuple[ScientificArticle, ...] = ()
    eligible_articles: tuple[ScientificArticle, ...] = ()
    deduplication_decisions: tuple[DeduplicationDecision, ...] = ()
    completed_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        for name in ("articles", "eligible_articles", "deduplication_decisions"):
            object.__setattr__(self, name, tuple(getattr(self, name)))


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
    publisher: Optional[str] = None
    publication_place: Optional[str] = None
    book_title: Optional[str] = None
    chapter_title: Optional[str] = None
    editors: list[str] = field(default_factory=list)
    url: Optional[str] = None
    accessed_at: Optional[date] = None
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
    verification_record: Optional[PublicationVerificationRecord] = None

    def __post_init__(self) -> None:
        if self.publication_year is None and self.year is not None:
            self.publication_year = self.year
        elif self.year is None and self.publication_year is not None:
            self.year = self.publication_year
        elif self.publication_year is not None and self.year is not None and self.publication_year != self.year:
            self.year = self.publication_year


@dataclass(frozen=True)
class Citation:
    citation_id: str = field(default_factory=lambda: uuid4().hex)
    article_id: str = ""
    source_type: str = "scientific_article"
    rendered_vancouver: Optional[str] = None
    verification_status: str = VerificationStatus.NOT_VERIFIED.value
    source_locator: Optional[str] = None
    citation_warning: Optional[str] = None


@dataclass(frozen=True)
class EvidenceClaim:
    claim_id: str = field(default_factory=lambda: uuid4().hex)
    claim_text: str = ""
    support_direction: str = SupportDirection.SUPPORTING.value
    verification_status: str = VerificationStatus.NOT_VERIFIED.value
    confidence: float = 0.0
    limitations: Optional[str] = None
    provenance: Optional[SourceProvenance] = None


@dataclass(frozen=True)
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


@dataclass(frozen=True)
class VerificationRun:
    verification_id: str = field(default_factory=lambda: uuid4().hex)
    article_id: str = ""
    source_type: str = "pubmed"
    checks: tuple[str, ...] = ()
    overall_status: str = VerificationStatus.NOT_VERIFIED.value
    notes: Optional[str] = None
    run_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "checks", tuple(self.checks))


ArticleRecord = ScientificArticle
LedgerEntry = EvidenceLedgerEntry
