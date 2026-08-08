from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Float, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from jmoraIs.config import get_database_url
from jmoraIs.verification import ArticleRecord, LedgerEntry


class Base(DeclarativeBase):
    pass


class ScientificArticle(Base):
    __tablename__ = "scientific_articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pmid: Mapped[Optional[str]] = mapped_column(String(20), unique=True, nullable=True)
    doi: Mapped[Optional[str]] = mapped_column(String(255), index=True, unique=True, nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    journal: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    abstract: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    authors: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(64), default="pubmed", nullable=False)
    source_locator: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    verification_status: Mapped[str] = mapped_column(String(40), default="NOT_VERIFIED", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


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
    verification_status: Mapped[str] = mapped_column(String(40), default="NOT_VERIFIED", nullable=False)
    support_direction: Mapped[str] = mapped_column(String(24), default="supporting", nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    limitations: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


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


def upsert_article(article: ArticleRecord, session: Session) -> ScientificArticle:
    if article.pmid:
        query = select(ScientificArticle).where(ScientificArticle.pmid == article.pmid)
    elif article.doi:
        query = select(ScientificArticle).where(ScientificArticle.doi == article.doi)
    else:
        query = select(ScientificArticle).where(ScientificArticle.title == article.title)

    existing = session.execute(query).scalar_one_or_none()
    if existing is None:
        existing = ScientificArticle(
            pmid=article.pmid,
            doi=article.doi,
            title=article.title,
            journal=article.journal,
            year=article.year,
            abstract=article.abstract,
            authors=",".join(article.authors) if article.authors else None,
            source=article.source,
            source_locator=article.source_locator,
            verification_status=article.verification_status,
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
