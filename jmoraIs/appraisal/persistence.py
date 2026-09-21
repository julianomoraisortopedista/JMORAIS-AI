from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Integer, JSON, String, UniqueConstraint, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from .governed import GovernedEvidence, GovernedEvidenceError
from jmoraIs.infrastructure.database_invariants import DuplicateStreamPosition, lock_stream


class GovernedEvidencePersistenceBase(DeclarativeBase):
    pass


class GovernedEvidenceVersionRow(GovernedEvidencePersistenceBase):
    __tablename__ = "governed_evidence_versions"
    __table_args__ = (
        UniqueConstraint("evidence_package_id", "stream_version", name="uq_governed_evidence_stream_version"),
        CheckConstraint("stream_version > 0", name="ck_governed_evidence_stream_version_positive"),
    )
    sequence_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    governed_evidence_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    evidence_package_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    stream_version: Mapped[int] = mapped_column(Integer, nullable=False)
    integrity_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


@event.listens_for(Session, "before_flush")
def _reject_governed_evidence_mutation(session, _flush, _instances):
    if any(isinstance(row, GovernedEvidenceVersionRow) for row in session.dirty):
        raise GovernedEvidenceError("GovernedEvidence UPDATE is prohibited")
    if any(isinstance(row, GovernedEvidenceVersionRow) for row in session.deleted):
        raise GovernedEvidenceError("GovernedEvidence DELETE is prohibited")


class SQLAlchemyGovernedEvidenceRepository:
    """PostgreSQL-ready append-only adapter; also supports SQLite integration tests."""

    def __init__(self, engine) -> None:
        self._sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def append(self, evidence: GovernedEvidence) -> None:
        payload = asdict(evidence)
        payload["issued_at"] = evidence.issued_at.isoformat()
        with self._sessions.begin() as session:
            lock_stream(session, "governed-evidence", evidence.evidence_package_id)
            current = session.scalar(select(func.max(GovernedEvidenceVersionRow.stream_version)).where(
                GovernedEvidenceVersionRow.evidence_package_id == evidence.evidence_package_id
            )) or 0
            session.add(GovernedEvidenceVersionRow(
                governed_evidence_id=evidence.governed_evidence_id,
                evidence_package_id=evidence.evidence_package_id,
                stream_version=current + 1,
                integrity_hash=evidence.integrity_hash,
                issued_at=evidence.issued_at,
                payload=payload,
            ))
            try:
                session.flush()
            except IntegrityError as exc:
                raise DuplicateStreamPosition("GovernedEvidence stream version conflict") from exc

    def get(self, governed_evidence_id: str) -> GovernedEvidence | None:
        with self._sessions() as session:
            row = session.scalar(select(GovernedEvidenceVersionRow).where(
                GovernedEvidenceVersionRow.governed_evidence_id == governed_evidence_id))
        return _decode(row.payload) if row else None

    def find_by_package_id(self, evidence_package_id: str) -> tuple[GovernedEvidence, ...]:
        return self.version_history(evidence_package_id)

    def version_history(self, evidence_package_id: str) -> tuple[GovernedEvidence, ...]:
        with self._sessions() as session:
            rows = session.scalars(select(GovernedEvidenceVersionRow).where(
                GovernedEvidenceVersionRow.evidence_package_id == evidence_package_id
            ).order_by(GovernedEvidenceVersionRow.stream_version)).all()
        return tuple(_decode(row.payload) for row in rows)


def _decode(payload: dict[str, Any]) -> GovernedEvidence:
    values = dict(payload)
    for key in ("applicability", "conflict_status", "support_directions",
                "provenance_references", "ledger_references", "limitations"):
        values[key] = tuple(values[key])
    values["issued_at"] = datetime.fromisoformat(values["issued_at"])
    return GovernedEvidence(**values)
