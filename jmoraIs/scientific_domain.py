from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
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


class HumanReviewStage(str, Enum):
    DRAFT = "DRAFT"
    AI_REVIEWED = "AI_REVIEWED"
    PHYSICIAN_REVIEWED = "PHYSICIAN_REVIEWED"
    FINAL = "FINAL"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


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
    source_name: str = ""
    source_locator: Optional[str] = None
    retrieved_at: datetime = field(default_factory=utc_now)
    record_hash: Optional[str] = None
    raw_payload: Optional[dict[str, Any]] = None


@dataclass
class ScientificArticle:
    article_id: str = field(default_factory=lambda: uuid4().hex)
    title: str = ""
    journal: Optional[str] = None
    year: Optional[int] = None
    pmid: Optional[str] = None
    doi: Optional[str] = None
    pmcid: Optional[str] = None
    abstract: Optional[str] = None
    authors: list[str] = field(default_factory=list)
    source_type: str = "pubmed"
    source_locator: Optional[str] = None
    verification_status: str = VerificationStatus.NOT_VERIFIED.value
    support_direction: str = SupportDirection.SUPPORTING.value
    provenance: Optional[SourceProvenance] = None
    human_review_status: str = HumanReviewStage.DRAFT.value
    normalized_title: Optional[str] = None
    raw_metadata: Optional[dict[str, Any]] = None


@dataclass
class Citation:
    citation_id: str = field(default_factory=lambda: uuid4().hex)
    article_id: str = ""
    source_type: str = "scientific_article"
    rendered_vancouver: Optional[str] = None
    verification_status: str = VerificationStatus.NOT_VERIFIED.value
    source_locator: Optional[str] = None


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
    supporting_passage: Optional[str] = None
    pmid: Optional[str] = None
    doi: Optional[str] = None
    pmcid: Optional[str] = None
    support_direction: str = SupportDirection.SUPPORTING.value
    verification_status: str = VerificationStatus.NOT_VERIFIED.value
    confidence: float = 0.0
    limitations: Optional[str] = None
    verified_at: datetime = field(default_factory=utc_now)


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
