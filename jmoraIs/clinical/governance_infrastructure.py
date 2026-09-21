from __future__ import annotations

from .review_governance import ConflictAdjudicationEvent, GovernedEvidenceLifecycleEvent


class InMemoryConflictAdjudicationRepository:
    def __init__(self, events: list[ConflictAdjudicationEvent] | None = None) -> None:
        self._events = events if events is not None else []

    def append(self, event: ConflictAdjudicationEvent) -> None:
        if any(item.event_id == event.event_id for item in self._events):
            raise ValueError("conflict events cannot be overwritten")
        history = self.history(event.conflict_id)
        if event.previous_event_hash != (history[-1].event_hash if history else None):
            raise ValueError("conflict hash chain is invalid")
        self._events.append(event)

    def history(self, conflict_id: str) -> tuple[ConflictAdjudicationEvent, ...]:
        return tuple(item for item in self._events if item.conflict_id == conflict_id)


class InMemoryGovernedEvidenceLifecycleRepository:
    def __init__(self, events: list[GovernedEvidenceLifecycleEvent] | None = None) -> None:
        self._events = events if events is not None else []

    def append(self, event: GovernedEvidenceLifecycleEvent) -> None:
        if any(item.event_id == event.event_id for item in self._events):
            raise ValueError("lifecycle events cannot be overwritten")
        history = self.history(event.governed_evidence_id)
        if event.previous_event_hash != (history[-1].event_hash if history else None):
            raise ValueError("lifecycle hash chain is invalid")
        self._events.append(event)

    def history(self, governed_evidence_id: str) -> tuple[GovernedEvidenceLifecycleEvent, ...]:
        return tuple(item for item in self._events if item.governed_evidence_id == governed_evidence_id)
