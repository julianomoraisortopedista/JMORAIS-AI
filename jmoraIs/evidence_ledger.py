from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

from jmoraIs.scientific_domain import SupportDirection


class LedgerEventType(str, Enum):
    EVIDENCE_ADDED = "EVIDENCE_ADDED"
    CORRECTION = "CORRECTION"
    SUPERSESSION = "SUPERSESSION"
    INVALIDATION = "INVALIDATION"
    RETRACTION = "RETRACTION"
    REPROCESSING = "REPROCESSING"


class SupportState(str, Enum):
    ACTIVE = "ACTIVE"
    CORRECTED = "CORRECTED"
    SUPERSEDED = "SUPERSEDED"
    INVALIDATED = "INVALIDATED"
    RETRACTED = "RETRACTED"


class LedgerInvariantError(ValueError):
    pass


class LedgerIntegrityError(RuntimeError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hash_payload(payload: Any) -> str:
    return sha256_text(_canonical_json(payload))


@dataclass(frozen=True)
class Claim:
    claim_id: str
    claim_text: str
    claim_hash: str
    created_at: datetime


@dataclass(frozen=True)
class EvidenceFragment:
    fragment_id: str
    source_name: str
    source_type: str
    source_locator: Optional[str]
    exact_location: Optional[str]
    passage: str
    pmid: Optional[str]
    doi: Optional[str]
    pmcid: Optional[str]
    payload_hash: str
    fragment_hash: str
    retrieved_at: datetime
    verification_version: str
    pipeline_version: str
    policy_version: str
    model_version: Optional[str]
    prompt_version: Optional[str]
    created_at: datetime


@dataclass(frozen=True)
class ClaimSupport:
    support_id: str
    claim_id: str
    fragment_id: str
    support_direction: str
    support_hash: str
    created_at: datetime


@dataclass(frozen=True)
class LedgerEvent:
    event_id: str
    claim_id: str
    event_type: str
    support_id: Optional[str]
    target_support_id: Optional[str]
    replacement_support_id: Optional[str]
    reason: Optional[str]
    occurred_at: datetime
    previous_event_hash: Optional[str]
    event_hash: str


@dataclass(frozen=True)
class LedgerSnapshot:
    claim: Claim
    as_of: Optional[datetime]
    support_states: tuple[tuple[str, str], ...]
    active_supports: tuple[ClaimSupport, ...]
    events: tuple[LedgerEvent, ...]


class AppendOnlyEvidenceLedger:
    """In-memory domain aggregate with an append-only, hash-chained event log."""

    def __init__(self) -> None:
        self._claims: dict[str, Claim] = {}
        self._fragments: dict[str, EvidenceFragment] = {}
        self._supports: dict[str, ClaimSupport] = {}
        self._events: list[LedgerEvent] = []

    @property
    def claims(self) -> tuple[Claim, ...]:
        return tuple(self._claims.values())

    @property
    def fragments(self) -> tuple[EvidenceFragment, ...]:
        return tuple(self._fragments.values())

    @property
    def supports(self) -> tuple[ClaimSupport, ...]:
        return tuple(self._supports.values())

    @property
    def events(self) -> tuple[LedgerEvent, ...]:
        return tuple(self._events)

    def create_claim(
        self,
        claim_text: str,
        *,
        claim_id: Optional[str] = None,
        created_at: Optional[datetime] = None,
    ) -> Claim:
        normalized = claim_text.strip()
        if not normalized:
            raise LedgerInvariantError("claim_text is required")
        identifier = claim_id or uuid4().hex
        claim_hash = sha256_text(normalized)
        existing = self._claims.get(identifier)
        if existing:
            if existing.claim_hash != claim_hash:
                raise LedgerInvariantError("claim_id cannot be reused with different text")
            return existing
        claim = Claim(identifier, normalized, claim_hash, created_at or utc_now())
        self._claims[identifier] = claim
        return claim

    def register_evidence(
        self,
        *,
        claim_id: str,
        source_name: str,
        source_type: str,
        passage: str,
        payload_hash: str,
        retrieved_at: datetime,
        verification_version: str,
        pipeline_version: str,
        policy_version: str,
        support_direction: str,
        source_locator: Optional[str] = None,
        exact_location: Optional[str] = None,
        pmid: Optional[str] = None,
        doi: Optional[str] = None,
        pmcid: Optional[str] = None,
        model_version: Optional[str] = None,
        prompt_version: Optional[str] = None,
        occurred_at: Optional[datetime] = None,
    ) -> tuple[EvidenceFragment, ClaimSupport, LedgerEvent]:
        if claim_id not in self._claims:
            raise LedgerInvariantError("claim must exist before evidence is registered")
        direction = self._normalize_direction(support_direction)
        if not source_name.strip() or not source_type.strip():
            raise LedgerInvariantError("source_name and source_type are required")
        if not passage.strip():
            raise LedgerInvariantError("exact evidence passage is required")
        if not payload_hash.strip():
            raise LedgerInvariantError("payload_hash is required")
        for version_name, version in (
            ("verification_version", verification_version),
            ("pipeline_version", pipeline_version),
            ("policy_version", policy_version),
        ):
            if not version.strip():
                raise LedgerInvariantError(f"{version_name} is required")

        fragment_data = {
            "source_name": source_name,
            "source_type": source_type,
            "source_locator": source_locator,
            "exact_location": exact_location,
            "passage": passage,
            "pmid": pmid,
            "doi": doi,
            "pmcid": pmcid,
            "payload_hash": payload_hash,
            "retrieved_at": retrieved_at.isoformat(),
            "verification_version": verification_version,
            "pipeline_version": pipeline_version,
            "policy_version": policy_version,
            "model_version": model_version,
            "prompt_version": prompt_version,
        }
        fragment_hash = hash_payload(fragment_data)
        fragment_id = fragment_hash
        fragment = self._fragments.get(fragment_id)
        if fragment is None:
            fragment = EvidenceFragment(
                fragment_id=fragment_id,
                source_name=source_name,
                source_type=source_type,
                source_locator=source_locator,
                exact_location=exact_location,
                passage=passage,
                pmid=pmid,
                doi=doi,
                pmcid=pmcid,
                payload_hash=payload_hash,
                fragment_hash=fragment_hash,
                retrieved_at=retrieved_at,
                verification_version=verification_version,
                pipeline_version=pipeline_version,
                policy_version=policy_version,
                model_version=model_version,
                prompt_version=prompt_version,
                created_at=occurred_at or utc_now(),
            )
            self._fragments[fragment_id] = fragment

        support_hash = hash_payload(
            {
                "claim_id": claim_id,
                "fragment_hash": fragment_hash,
                "support_direction": direction,
            }
        )
        support_id = support_hash
        support = self._supports.get(support_id)
        event_type = LedgerEventType.REPROCESSING if support else LedgerEventType.EVIDENCE_ADDED
        if support is None:
            support = ClaimSupport(
                support_id=support_id,
                claim_id=claim_id,
                fragment_id=fragment_id,
                support_direction=direction,
                support_hash=support_hash,
                created_at=occurred_at or utc_now(),
            )
            self._supports[support_id] = support
        event = self._append_event(
            claim_id=claim_id,
            event_type=event_type,
            support_id=support_id,
            target_support_id=support_id if event_type == LedgerEventType.REPROCESSING else None,
            reason="deterministic reprocessing" if event_type == LedgerEventType.REPROCESSING else None,
            occurred_at=occurred_at,
        )
        return fragment, support, event

    def append_lifecycle_event(
        self,
        *,
        claim_id: str,
        event_type: LedgerEventType | str,
        target_support_id: str,
        replacement_support_id: Optional[str] = None,
        reason: Optional[str] = None,
        occurred_at: Optional[datetime] = None,
    ) -> LedgerEvent:
        event_kind = LedgerEventType(event_type)
        if event_kind not in {
            LedgerEventType.CORRECTION,
            LedgerEventType.SUPERSESSION,
            LedgerEventType.INVALIDATION,
            LedgerEventType.RETRACTION,
        }:
            raise LedgerInvariantError("lifecycle event type is not permitted")
        if claim_id not in self._claims:
            raise LedgerInvariantError("unknown claim")
        target = self._supports.get(target_support_id)
        if target is None or target.claim_id != claim_id:
            raise LedgerInvariantError("target support does not belong to claim")
        if event_kind in {LedgerEventType.CORRECTION, LedgerEventType.SUPERSESSION}:
            replacement = self._supports.get(replacement_support_id or "")
            if replacement is None or replacement.claim_id != claim_id:
                raise LedgerInvariantError("replacement support is required for correction/supersession")
        elif replacement_support_id is not None:
            raise LedgerInvariantError("replacement support is not allowed for this event")
        return self._append_event(
            claim_id=claim_id,
            event_type=event_kind,
            support_id=None,
            target_support_id=target_support_id,
            replacement_support_id=replacement_support_id,
            reason=reason,
            occurred_at=occurred_at,
        )

    def reconstruct(self, claim_id: str, *, as_of: Optional[datetime] = None) -> LedgerSnapshot:
        claim = self._claims.get(claim_id)
        if claim is None:
            raise LedgerInvariantError("unknown claim")
        events = tuple(
            event
            for event in self._events
            if event.claim_id == claim_id and (as_of is None or event.occurred_at <= as_of)
        )
        states: dict[str, str] = {}
        for event in events:
            kind = LedgerEventType(event.event_type)
            if kind == LedgerEventType.EVIDENCE_ADDED and event.support_id:
                states[event.support_id] = SupportState.ACTIVE.value
            elif kind == LedgerEventType.REPROCESSING:
                continue
            elif kind == LedgerEventType.CORRECTION and event.target_support_id:
                states[event.target_support_id] = SupportState.CORRECTED.value
                if event.replacement_support_id:
                    states[event.replacement_support_id] = SupportState.ACTIVE.value
            elif kind == LedgerEventType.SUPERSESSION and event.target_support_id:
                states[event.target_support_id] = SupportState.SUPERSEDED.value
                if event.replacement_support_id:
                    states[event.replacement_support_id] = SupportState.ACTIVE.value
            elif kind == LedgerEventType.INVALIDATION and event.target_support_id:
                states[event.target_support_id] = SupportState.INVALIDATED.value
            elif kind == LedgerEventType.RETRACTION and event.target_support_id:
                states[event.target_support_id] = SupportState.RETRACTED.value
        active = tuple(
            self._supports[support_id]
            for support_id, state in states.items()
            if state == SupportState.ACTIVE.value
        )
        return LedgerSnapshot(
            claim=claim,
            as_of=as_of,
            support_states=tuple(sorted(states.items())),
            active_supports=active,
            events=events,
        )

    def verify_integrity(self, claim_id: Optional[str] = None) -> bool:
        previous_by_claim: dict[str, Optional[str]] = {}
        for event in self._events:
            if claim_id is not None and event.claim_id != claim_id:
                continue
            expected_previous = previous_by_claim.get(event.claim_id)
            if event.previous_event_hash != expected_previous:
                raise LedgerIntegrityError("event chain predecessor mismatch")
            expected_hash = self._calculate_event_hash(
                event_id=event.event_id,
                claim_id=event.claim_id,
                event_type=event.event_type,
                support_id=event.support_id,
                target_support_id=event.target_support_id,
                replacement_support_id=event.replacement_support_id,
                reason=event.reason,
                occurred_at=event.occurred_at,
                previous_event_hash=event.previous_event_hash,
            )
            if event.event_hash != expected_hash:
                raise LedgerIntegrityError("event hash mismatch")
            previous_by_claim[event.claim_id] = event.event_hash
        return True

    def _append_event(
        self,
        *,
        claim_id: str,
        event_type: LedgerEventType,
        support_id: Optional[str],
        target_support_id: Optional[str] = None,
        replacement_support_id: Optional[str] = None,
        reason: Optional[str] = None,
        occurred_at: Optional[datetime] = None,
    ) -> LedgerEvent:
        timestamp = occurred_at or utc_now()
        previous_hash = next(
            (event.event_hash for event in reversed(self._events) if event.claim_id == claim_id),
            None,
        )
        event_id = uuid4().hex
        event_hash = self._calculate_event_hash(
            event_id=event_id,
            claim_id=claim_id,
            event_type=event_type.value,
            support_id=support_id,
            target_support_id=target_support_id,
            replacement_support_id=replacement_support_id,
            reason=reason,
            occurred_at=timestamp,
            previous_event_hash=previous_hash,
        )
        event = LedgerEvent(
            event_id=event_id,
            claim_id=claim_id,
            event_type=event_type.value,
            support_id=support_id,
            target_support_id=target_support_id,
            replacement_support_id=replacement_support_id,
            reason=reason,
            occurred_at=timestamp,
            previous_event_hash=previous_hash,
            event_hash=event_hash,
        )
        self._events.append(event)
        return event

    @staticmethod
    def _calculate_event_hash(
        *,
        event_id: str,
        claim_id: str,
        event_type: str,
        support_id: Optional[str],
        target_support_id: Optional[str],
        replacement_support_id: Optional[str],
        reason: Optional[str],
        occurred_at: datetime,
        previous_event_hash: Optional[str],
    ) -> str:
        return hash_payload(
            {
                "event_id": event_id,
                "claim_id": claim_id,
                "event_type": event_type,
                "support_id": support_id,
                "target_support_id": target_support_id,
                "replacement_support_id": replacement_support_id,
                "reason": reason,
                "occurred_at": occurred_at.isoformat(),
                "previous_event_hash": previous_event_hash,
            }
        )

    @staticmethod
    def _normalize_direction(direction: str) -> str:
        normalized = str(direction).upper()
        try:
            return SupportDirection(normalized).value
        except ValueError as exc:
            raise LedgerInvariantError(f"invalid support direction: {direction}") from exc
