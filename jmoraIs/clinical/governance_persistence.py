from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint, event, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from .governed import GovernedDecisionAuditEvent
from .review_governance import (
    ConflictAdjudicationEvent, ConflictAdjudicationState,
    GovernedEvidenceLifecycleEvent, GovernedEvidenceLifecycleStatus, ReevaluationTrigger,
    ReviewerIdentity, ReviewerRole, ReviewerStatus,
)
from jmoraIs.infrastructure.database_invariants import (
    ConcurrencyConflict, DuplicateStreamPosition, HashChainFailure, lock_stream,
)


class ClinicalGovernancePersistenceError(RuntimeError):
    pass


class ClinicalGovernancePersistenceBase(DeclarativeBase):
    pass


class ReviewerIdentityRow(ClinicalGovernancePersistenceBase):
    __tablename__ = "reviewer_identities"
    reviewer_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    active: Mapped[bool] = mapped_column(nullable=False)
    organization_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    authorization_policy_version: Mapped[str] = mapped_column(String(32), nullable=False)


class ClinicalAuditEventRow(ClinicalGovernancePersistenceBase):
    __tablename__ = "governed_clinical_audit_events"
    __table_args__ = (
        UniqueConstraint("case_id", "stream_position", name="uq_clinical_audit_stream_position"),
        CheckConstraint("stream_position > 0", name="ck_clinical_audit_position_positive"),
    )
    sequence_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    case_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    reviewer_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("reviewer_identities.reviewer_id", ondelete="RESTRICT"), nullable=True,
    )
    stream_position: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_event_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ConflictAdjudicationEventRow(ClinicalGovernancePersistenceBase):
    __tablename__ = "clinical_conflict_adjudication_events"
    __table_args__ = (
        UniqueConstraint("conflict_id", "stream_position", name="uq_conflict_stream_position"),
        CheckConstraint("stream_position > 0", name="ck_conflict_position_positive"),
    )
    sequence_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    conflict_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    stream_position: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_event_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class GovernedEvidenceLifecycleEventRow(ClinicalGovernancePersistenceBase):
    __tablename__ = "governed_evidence_lifecycle_events"
    __table_args__ = (
        UniqueConstraint("governed_evidence_id", "stream_position", name="uq_lifecycle_stream_position"),
        CheckConstraint("stream_position > 0", name="ck_lifecycle_position_positive"),
    )
    sequence_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    governed_evidence_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    stream_position: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_event_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


_IMMUTABLE = (ClinicalAuditEventRow, ConflictAdjudicationEventRow, GovernedEvidenceLifecycleEventRow)


@event.listens_for(Session, "before_flush")
def _reject_governance_mutation(session, _flush, _instances):
    if any(isinstance(row, _IMMUTABLE) for row in session.dirty):
        raise ClinicalGovernancePersistenceError("clinical governance UPDATE is prohibited")
    if any(isinstance(row, _IMMUTABLE) for row in session.deleted):
        raise ClinicalGovernancePersistenceError("clinical governance DELETE is prohibited")


def _payload(item):
    value = asdict(item)
    value["occurred_at"] = item.occurred_at.isoformat()
    for key, item_value in tuple(value.items()):
        if isinstance(item_value, tuple): value[key] = list(item_value)
        elif isinstance(item_value, Enum): value[key] = item_value.value
        elif isinstance(item_value, list): value[key] = [entry.value if isinstance(entry, Enum) else entry for entry in item_value]
    return value


from enum import Enum


class SQLAlchemyGovernedDecisionAuditRepository:
    def __init__(self, engine): self._sessions = sessionmaker(bind=engine, expire_on_commit=False)
    def append(self, item):
        self._append(ClinicalAuditEventRow, "case_id", item.case_id, item)
    def _append(self, row_type, owner_field, owner_id, item):
        with self._sessions.begin() as s:
            lock_stream(s, row_type.__tablename__, owner_id)
            last = s.scalar(select(row_type).where(getattr(row_type, owner_field)==owner_id).order_by(row_type.stream_position.desc()).limit(1))
            expected = last.event_hash if last else None
            if item.previous_event_hash != expected: raise ConcurrencyConflict("audit stream advanced; retry from current history")
            row = row_type(event_id=item.event_id, event_hash=item.event_hash, occurred_at=item.occurred_at,
                stream_position=(last.stream_position + 1 if last else 1), previous_event_hash=item.previous_event_hash,
                payload=_payload(item),
                **({"reviewer_id": item.reviewer_id} if row_type is ClinicalAuditEventRow else {}),
                **{owner_field: owner_id})
            s.add(row)
            try: s.flush()
            except IntegrityError as exc: raise DuplicateStreamPosition("audit stream position conflict") from exc
    def history(self, case_id):
        with self._sessions() as s: rows=s.scalars(select(ClinicalAuditEventRow).where(ClinicalAuditEventRow.case_id==case_id).order_by(ClinicalAuditEventRow.sequence_id)).all()
        return tuple(_audit(row.payload) for row in rows)


class SQLAlchemyConflictAdjudicationRepository:
    def __init__(self, engine): self._sessions = sessionmaker(bind=engine, expire_on_commit=False)
    def append(self, item):
        SQLAlchemyGovernedDecisionAuditRepository._append(self, ConflictAdjudicationEventRow, "conflict_id", item.conflict_id, item)
    def history(self, conflict_id):
        with self._sessions() as s: rows=s.scalars(select(ConflictAdjudicationEventRow).where(ConflictAdjudicationEventRow.conflict_id==conflict_id).order_by(ConflictAdjudicationEventRow.sequence_id)).all()
        return tuple(_conflict(row.payload) for row in rows)


class SQLAlchemyGovernedEvidenceLifecycleRepository:
    def __init__(self, engine): self._sessions = sessionmaker(bind=engine, expire_on_commit=False)
    def append(self, item):
        SQLAlchemyGovernedDecisionAuditRepository._append(self, GovernedEvidenceLifecycleEventRow, "governed_evidence_id", item.governed_evidence_id, item)
    def history(self, governed_evidence_id):
        with self._sessions() as s: rows=s.scalars(select(GovernedEvidenceLifecycleEventRow).where(GovernedEvidenceLifecycleEventRow.governed_evidence_id==governed_evidence_id).order_by(GovernedEvidenceLifecycleEventRow.sequence_id)).all()
        return tuple(_lifecycle(row.payload) for row in rows)


def _dt(value): return datetime.fromisoformat(value) if isinstance(value, str) else value
def _audit(v): return GovernedDecisionAuditEvent(**{**v, "occurred_at":_dt(v["occurred_at"]), "governed_evidence_ids":tuple(v["governed_evidence_ids"]), "recommendation_ids":tuple(v["recommendation_ids"]), "weighting_decisions":tuple(v["weighting_decisions"]), "conflict_decisions":tuple(v["conflict_decisions"]), "confidence_inputs":tuple(v["confidence_inputs"])})
def _conflict(v): return ConflictAdjudicationEvent(**{**v, "state":ConflictAdjudicationState(v["state"]), "directions":tuple(v["directions"]), "occurred_at":_dt(v["occurred_at"])})
def _lifecycle(v): return GovernedEvidenceLifecycleEvent(**{**v, "status":GovernedEvidenceLifecycleStatus(v["status"]), "triggers":tuple(ReevaluationTrigger(x) for x in v["triggers"]), "occurred_at":_dt(v["occurred_at"])})


class PostgreSQLReviewerIdentityRepository:
    """Durable authoritative reviewer directory adapter; SSO remains out of scope."""

    def __init__(self, engine):
        self._engine = engine
        self._sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def readiness(self):
        from jmoraIs.api.security import ReadinessCheck
        try:
            with self._engine.connect() as connection:
                connection.execute(text("SELECT 1 FROM reviewer_identities LIMIT 1"))
            return ReadinessCheck("reviewer_identity_repository", True, "AVAILABLE")
        except Exception:
            return ReadinessCheck("reviewer_identity_repository", False, "UNAVAILABLE")

    def save(self, identity: ReviewerIdentity) -> None:
        with self._sessions.begin() as session:
            session.merge(ReviewerIdentityRow(
                reviewer_id=identity.reviewer_id, role=identity.role.value,
                status=identity.status.value, active=identity.active,
                organization_id=identity.organization_id, tenant_id=identity.tenant_id,
                created_at=identity.created_at, updated_at=identity.updated_at,
                authorization_policy_version=identity.authorization_policy_version,
            ))

    def resolve(self, reviewer_id: str) -> ReviewerIdentity | None:
        with self._sessions() as session:
            row = session.get(ReviewerIdentityRow, reviewer_id)
        if row is None:
            return None
        return ReviewerIdentity(
            reviewer_id=row.reviewer_id, role=ReviewerRole(row.role), active=row.active,
            status=ReviewerStatus(row.status), organization_id=row.organization_id,
            tenant_id=row.tenant_id, created_at=row.created_at, updated_at=row.updated_at,
            authorization_policy_version=row.authorization_policy_version,
        )

    def may_review(self, identity: ReviewerIdentity) -> bool:
        persisted = self.resolve(identity.reviewer_id)
        return bool(
            persisted is not None
            and persisted.role == identity.role
            and persisted.organization_id == identity.organization_id
            and persisted.tenant_id == identity.tenant_id
            and persisted.authorization_policy_version == identity.authorization_policy_version
            and persisted.active
            and persisted.status == ReviewerStatus.ACTIVE
            and persisted.role in set(ReviewerRole)
        )
