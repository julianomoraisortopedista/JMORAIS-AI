from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint, create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from jmoraIs.application.evidence_packages import (
    ClaimEvidenceRelationship, EvidencePackage, PackageCatalogRecord,
    PackageLedgerAssociation, PackageVersionRecord, PublicationIdentity,
)
from jmoraIs.evidence_ledger import AppendOnlyEvidenceLedger, Claim, ClaimSupport, EvidenceFragment, LedgerEvent
from jmoraIs.infrastructure.package_catalog import PackageCatalogConflict
from jmoraIs.infrastructure.database_invariants import ConcurrencyConflict, lock_stream


class PackageCatalogBase(DeclarativeBase): pass


class CanonicalClaimRow(PackageCatalogBase):
    __tablename__ = "canonical_ledger_claims"
    claim_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class CanonicalFragmentRow(PackageCatalogBase):
    __tablename__ = "canonical_ledger_fragments"
    fragment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class CanonicalSupportRow(PackageCatalogBase):
    __tablename__ = "canonical_ledger_supports"
    support_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    claim_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class CanonicalEventRow(PackageCatalogBase):
    __tablename__ = "canonical_ledger_events"
    __table_args__ = (
        UniqueConstraint("claim_id", "stream_position", name="uq_canonical_ledger_stream_position"),
        CheckConstraint("stream_position > 0", name="ck_canonical_ledger_position_positive"),
    )
    sequence_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    claim_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    stream_position: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_event_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    event_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class PackageCatalogRow(PackageCatalogBase):
    __tablename__ = "evidence_package_catalog"
    package_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    package_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    association_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PackageVersionRow(PackageCatalogBase):
    __tablename__ = "evidence_package_versions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    package_id: Mapped[str] = mapped_column(ForeignKey("evidence_package_catalog.package_id", ondelete="RESTRICT"), nullable=False, index=True)
    package_version: Mapped[str] = mapped_column(String(64), nullable=False)
    integrity_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


_IMMUTABLE = (CanonicalClaimRow, CanonicalFragmentRow, CanonicalSupportRow, CanonicalEventRow, PackageCatalogRow, PackageVersionRow)


@event.listens_for(Session, "before_flush")
def reject_mutation(session, _flush, _instances):
    if any(isinstance(row, _IMMUTABLE) for row in session.dirty): raise PackageCatalogConflict("canonical ledger UPDATE is prohibited")
    if any(isinstance(row, _IMMUTABLE) for row in session.deleted): raise PackageCatalogConflict("canonical ledger DELETE is prohibited")


def _encode(item):
    data = asdict(item)
    for key, value in tuple(data.items()):
        if isinstance(value, datetime): data[key] = value.isoformat()
    return data


def _dt(value): return datetime.fromisoformat(value) if isinstance(value, str) else value


class PostgreSQLCanonicalLedger(AppendOnlyEvidenceLedger):
    """PostgreSQL event stream is canonical; memory is a replayed projection."""
    def __init__(self, engine, *, claim_ids: tuple[str, ...] | None = None):
        super().__init__()
        self._sessions = sessionmaker(bind=engine, expire_on_commit=False)
        self._claim_ids = tuple(dict.fromkeys(claim_ids)) if claim_ids is not None else None
        if self._claim_ids is not None and not self._claim_ids:
            raise PackageCatalogConflict("scoped canonical ledger requires claim identities")
        self._replay()

    def _replay(self):
        with self._sessions() as session:
            claim_query = select(CanonicalClaimRow)
            support_query = select(CanonicalSupportRow)
            event_query = select(CanonicalEventRow).order_by(CanonicalEventRow.sequence_id)
            if self._claim_ids is not None:
                claim_query = claim_query.where(CanonicalClaimRow.claim_id.in_(self._claim_ids))
                support_query = support_query.where(CanonicalSupportRow.claim_id.in_(self._claim_ids))
                event_query = event_query.where(CanonicalEventRow.claim_id.in_(self._claim_ids))
            claims = session.scalars(claim_query).all()
            supports = session.scalars(support_query).all()
            fragment_ids = tuple({row.payload["fragment_id"] for row in supports})
            fragment_query = select(CanonicalFragmentRow)
            if self._claim_ids is not None:
                fragment_query = fragment_query.where(CanonicalFragmentRow.fragment_id.in_(fragment_ids))
            fragments = session.scalars(fragment_query).all() if fragment_ids or self._claim_ids is None else []
            events = session.scalars(event_query).all()
        self._claims = {r.claim_id: Claim(**{**r.payload, "created_at": _dt(r.payload["created_at"])}) for r in claims}
        self._fragments = {r.fragment_id: EvidenceFragment(**{**r.payload, "retrieved_at": _dt(r.payload["retrieved_at"]), "created_at": _dt(r.payload["created_at"])}) for r in fragments}
        self._supports = {r.support_id: ClaimSupport(**{**r.payload, "created_at": _dt(r.payload["created_at"])}) for r in supports}
        self._events = [LedgerEvent(**{**r.payload, "occurred_at": _dt(r.payload["occurred_at"])}) for r in events]
        self.verify_integrity()

    def create_claim(self, *args, **kwargs):
        before = set(self._claims); item = super().create_claim(*args, **kwargs)
        if item.claim_id not in before:
            with self._sessions.begin() as s: s.add(CanonicalClaimRow(claim_id=item.claim_id, payload=_encode(item)))
        return item

    def register_evidence(self, **kwargs):
        old_fragments, old_supports, old_events = set(self._fragments), set(self._supports), {e.event_id for e in self._events}
        fragment, support, ledger_event = super().register_evidence(**kwargs)
        with self._sessions.begin() as s:
            if fragment.fragment_id not in old_fragments: s.add(CanonicalFragmentRow(fragment_id=fragment.fragment_id, payload=_encode(fragment)))
            if support.support_id not in old_supports: s.add(CanonicalSupportRow(support_id=support.support_id, claim_id=support.claim_id, payload=_encode(support)))
            if ledger_event.event_id not in old_events: self._add_event(s, ledger_event)
        return fragment, support, ledger_event

    def append_lifecycle_event(self, **kwargs):
        item = super().append_lifecycle_event(**kwargs)
        with self._sessions.begin() as s: self._add_event(s, item)
        return item

    @staticmethod
    def _add_event(session, item):
        lock_stream(session, "canonical_ledger_events", item.claim_id)
        last = session.scalar(select(CanonicalEventRow).where(
            CanonicalEventRow.claim_id == item.claim_id
        ).order_by(CanonicalEventRow.stream_position.desc()).limit(1))
        expected = last.event_hash if last else None
        if item.previous_event_hash != expected:
            raise ConcurrencyConflict("canonical ledger stream advanced; replay and retry")
        session.add(CanonicalEventRow(
            event_id=item.event_id, claim_id=item.claim_id,
            stream_position=(last.stream_position + 1 if last else 1),
            previous_event_hash=item.previous_event_hash,
            event_hash=item.event_hash, occurred_at=item.occurred_at, payload=_encode(item),
        ))


class PostgreSQLPackageCatalogRepository:
    def __init__(self, engine):
        self._engine = engine; self._sessions = sessionmaker(bind=engine, expire_on_commit=False)

    @classmethod
    def from_url(cls, url): return cls(create_engine(url, future=True))

    def append(self, record, version):
        if not isinstance(record.ledger, PostgreSQLCanonicalLedger): raise PackageCatalogConflict("package must reference the canonical PostgreSQL ledger")
        if record.association.package_id != record.package.package_id or tuple(record.package.ledger_references) != record.association.ledger_event_hashes: raise PackageCatalogConflict("ledger association integrity mismatch")
        canonical_hashes = {e.event_hash for e in record.ledger.events}
        if not set(record.association.ledger_event_hashes).issubset(canonical_hashes): raise PackageCatalogConflict("ledger events are absent from canonical stream")
        with self._sessions.begin() as s:
            s.add(PackageCatalogRow(package_id=record.package.package_id, package_payload=_package_to_dict(record.package), association_payload=asdict(record.association), recorded_at=record.recorded_at))
            s.add(PackageVersionRow(**asdict(version)))
            try: s.flush()
            except IntegrityError as exc: raise PackageCatalogConflict("package catalog records cannot be overwritten") from exc

    def get(self, package_id):
        with self._sessions() as s: row = s.get(PackageCatalogRow, package_id)
        if row is None: return None
        association = PackageLedgerAssociation(**{**row.association_payload, "claim_ids": tuple(row.association_payload["claim_ids"]), "support_ids": tuple(row.association_payload["support_ids"]), "ledger_event_hashes": tuple(row.association_payload["ledger_event_hashes"])})
        return PackageCatalogRecord(package=_package_from_dict(row.package_payload), association=association,
            ledger=PostgreSQLCanonicalLedger(self._engine, claim_ids=association.claim_ids),
            recorded_at=row.recorded_at)

    def version_history(self, package_id):
        with self._sessions() as s: rows = s.scalars(select(PackageVersionRow).where(PackageVersionRow.package_id == package_id).order_by(PackageVersionRow.id)).all()
        return tuple(PackageVersionRecord(package_id=r.package_id, package_version=r.package_version, integrity_hash=r.integrity_hash, recorded_at=r.recorded_at) for r in rows)


def _package_to_dict(package):
    data = asdict(package); data.update(created_at=package.created_at.isoformat(), expires_at=package.expires_at.isoformat() if package.expires_at else None, revalidation_required_at=package.revalidation_required_at.isoformat() if package.revalidation_required_at else None); return data


def _package_from_dict(data):
    return EvidencePackage(package_id=data["package_id"], package_version=data["package_version"], verification_status=data["verification_status"], publication_identities=tuple(PublicationIdentity(**x) for x in data["publication_identities"]), claim_evidence_relationships=tuple(ClaimEvidenceRelationship(**x) for x in data["claim_evidence_relationships"]), provenance_references=tuple(data["provenance_references"]), ledger_references=tuple(data["ledger_references"]), verification_references=tuple(data["verification_references"]), policy_version=data["policy_version"], pipeline_version=data["pipeline_version"], created_at=_dt(data["created_at"]), expires_at=_dt(data.get("expires_at")), revalidation_required_at=_dt(data.get("revalidation_required_at")), integrity_hash=data["integrity_hash"])
