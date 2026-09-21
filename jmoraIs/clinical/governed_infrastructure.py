from __future__ import annotations

from .governed import GovernedDecisionAuditEvent


class InMemoryGovernedDecisionAuditRepository:
    """Append-only reference adapter for governed clinical decisions."""

    def __init__(self) -> None:
        self._events: list[GovernedDecisionAuditEvent] = []

    def append(self, event: GovernedDecisionAuditEvent) -> None:
        if any(item.event_id == event.event_id for item in self._events):
            raise ValueError("audit events cannot be overwritten")
        history = self.history(event.case_id)
        expected = history[-1].event_hash if history else None
        if event.previous_event_hash != expected:
            raise ValueError("audit hash chain is invalid")
        self._events.append(event)

    def history(self, case_id: str) -> tuple[GovernedDecisionAuditEvent, ...]:
        return tuple(item for item in self._events if item.case_id == case_id)
