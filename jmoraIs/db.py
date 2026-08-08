from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import DateTime, Float, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from jmoraIs.config import get_database_url
from jmoraIs.verification import ArticleRecord, LedgerEntry


class Base(DeclarativeBase):
    pass


class ScientificArticle(Base):
    __tablename__ = "scientific_articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[str] = mapped_column(String(64), unique=True, default=lambda: uuid4().hex, nullable=False)
    pmid: Mapped[Optional[str]] = mapped_column(String(20), unique=True, nullable=True)
    doi: Mapped[Optional[str]] = mapped_column(String(255), index=True, unique=True, nullable=True)
    pmcid: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    journal: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    abstract: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    authors: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(64), default="pubmed", nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), default="pubmed", nullable=False)
    source_locator: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    verification_status: Mapped[str] = mapped_column(String(40), default="NOT_VERIFIED", nullable=False)
    human_review_status: Mapped[str] = mapped_column(String(32), default="DRAFT", nullable=False)
    normalized_title: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class Author(Base):
    __tablename__ = "authors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    author_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    orcid: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    affiliation: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class ArticleAuthor(Base):
    __tablename__ = "article_authors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[int] = mapped_column(Integer, nullable=False)
    author_id: Mapped[int] = mapped_column(Integer, nullable=False)
    author_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_corresponding: Mapped[bool] = mapped_column(default=False, nullable=False)


class MeshTerm(Base):
    __tablename__ = "mesh_terms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    term: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)


class ArticleMeshTerm(Base):
    __tablename__ = "article_mesh_terms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[int] = mapped_column(Integer, nullable=False)
    mesh_term_id: Mapped[int] = mapped_column(Integer, nullable=False)


class ArticleTopic(Base):
    __tablename__ = "article_topics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[int] = mapped_column(Integer, nullable=False)
    topic: Mapped[str] = mapped_column(String(255), nullable=False)
    score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)


class SourceProvenance(Base):
    __tablename__ = "source_provenance"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_name: Mapped[str] = mapped_column(String(64), nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_locator: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    record_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    raw_payload: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class Citation(Base):
    __tablename__ = "citations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    citation_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    article_id: Mapped[int] = mapped_column(Integer, nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    rendered_vancouver: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    verification_status: Mapped[str] = mapped_column(String(40), default="NOT_VERIFIED", nullable=False)
    source_locator: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class EvidenceClaim(Base):
    __tablename__ = "evidence_claims"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    claim_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    support_direction: Mapped[str] = mapped_column(String(24), default="SUPPORTING", nullable=False)
    verification_status: Mapped[str] = mapped_column(String(40), default="NOT_VERIFIED", nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    limitations: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    provenance_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class EvidenceLedger(Base):
    __tablename__ = "evidence_ledger"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    claim_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[int] = mapped_column(Integer, nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_locator: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    supporting_passage: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    pmid: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    doi: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    pmcid: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    verification_status: Mapped[str] = mapped_column(String(40), default="NOT_VERIFIED", nullable=False)
    support_direction: Mapped[str] = mapped_column(String(24), default="SUPPORTING", nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    limitations: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class SearchRun(Base):
    __tablename__ = "search_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    search_id: Mapped[str] = mapped_column(String(64), unique=True, default=lambda: uuid4().hex, nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(64), default="pubmed", nullable=False)
    result_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="completed", nullable=False)


class VerificationRun(Base):
    __tablename__ = "verification_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    verification_id: Mapped[str] = mapped_column(String(64), unique=True, default=lambda: uuid4().hex, nullable=False)
    article_id: Mapped[int] = mapped_column(Integer, nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), default="pubmed", nullable=False)
    checks: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    overall_status: Mapped[str] = mapped_column(String(40), default="NOT_VERIFIED", nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class ClinicalDecision(Base):
    __tablename__ = "clinical_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    condition: Mapped[str] = mapped_column(Text, nullable=False)
    recommendation: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    evidence_strength: Mapped[str] = mapped_column(String(16), default="limited", nullable=False)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    supporting_claims: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    caution: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_ids: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


def get_engine():
    database_url = get_database_url()
    return create_engine(database_url, future=True)


def create_tables() -> None:
    Base.metadata.create_all(bind=get_engine())


def _article_query(article: ArticleRecord):
    if article.doi:
        return select(ScientificArticle).where(ScientificArticle.doi == article.doi)
    if article.pmid:
        return select(ScientificArticle).where(ScientificArticle.pmid == article.pmid)
    if article.pmcid:
        return select(ScientificArticle).where(ScientificArticle.pmcid == article.pmcid)
    return select(ScientificArticle).where(ScientificArticle.normalized_title == (article.normalized_title or article.title.strip().lower()))


def upsert_article(article: ArticleRecord, session: Session) -> ScientificArticle:
    query = _article_query(article)
    existing = session.execute(query).scalar_one_or_none()
    if existing is None:
        existing = ScientificArticle(
            article_id=article.article_id,
            pmid=article.pmid,
            doi=article.doi,
            pmcid=article.pmcid,
            title=article.title,
            journal=article.journal,
            year=article.year,
            abstract=article.abstract,
            authors=",".join(article.authors) if article.authors else None,
            source=getattr(article, "source_type", getattr(article, "source", "pubmed")),
            source_type=getattr(article, "source_type", getattr(article, "source", "pubmed")),
            source_locator=getattr(article, "source_locator", None),
            verification_status=article.verification_status,
            human_review_status=getattr(article, "human_review_status", "DRAFT"),
            normalized_title=getattr(article, "normalized_title", None) or article.title.strip().lower(),
        )
        session.add(existing)
        session.commit()
        session.refresh(existing)
    return existing


def store_ledger_entry(entry: LedgerEntry, session: Session) -> EvidenceLedger:
    ledger = EvidenceLedger(
        claim_id=entry.claim_id,
        claim_text=entry.claim_text,
        source_id=entry.source_id,
        source_type=entry.source_type,
        source_locator=entry.source_locator,
        supporting_passage=entry.supporting_passage,
        pmid=entry.pmid,
        doi=entry.doi,
        pmcid=getattr(entry, "pmcid", None),
        verification_status=entry.verification_status,
        support_direction=entry.support_direction,
        confidence=entry.confidence,
        limitations=entry.limitations,
    )
    session.add(ledger)
    session.commit()
    session.refresh(ledger)
    return ledger


def store_clinical_decision(decision: Any, session: Session) -> ClinicalDecision:
    record = ClinicalDecision(
        condition=decision.condition,
        recommendation=decision.recommendation,
        confidence=decision.confidence,
        evidence_strength=decision.evidence_strength,
        reasoning=decision.reasoning,
        supporting_claims="|".join(decision.supporting_claims),
        caution="|".join(decision.caution),
        source_ids="|".join(decision.source_ids),
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


__all__ = [
    "Base",
    "ScientificArticle",
    "Author",
    "ArticleAuthor",
    "MeshTerm",
    "ArticleMeshTerm",
    "ArticleTopic",
    "SourceProvenance",
    "Citation",
    "EvidenceClaim",
    "EvidenceLedger",
    "SearchRun",
    "VerificationRun",
    "ClinicalDecision",
    "get_engine",
    "create_tables",
    "upsert_article",
    "store_ledger_entry",
    "store_clinical_decision",
]
