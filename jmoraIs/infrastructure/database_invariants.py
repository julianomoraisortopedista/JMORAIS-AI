from __future__ import annotations

from sqlalchemy import text


class DatabaseInvariantError(RuntimeError):
    """Base error for persistent history invariants; contains no record payload."""


class AppendOnlyViolation(DatabaseInvariantError):
    pass


class ConcurrencyConflict(DatabaseInvariantError):
    pass


class PersistentIntegrityViolation(DatabaseInvariantError):
    pass


class DuplicateStreamPosition(ConcurrencyConflict):
    pass


class HashChainFailure(PersistentIntegrityViolation):
    pass


class TransactionRollback(DatabaseInvariantError):
    pass


def lock_stream(session, namespace: str, stream_id: str) -> None:
    """Serialize one logical PostgreSQL stream for the current transaction."""
    if session.bind.dialect.name == "postgresql":
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:stream_key, 0))"),
            {"stream_key": f"{namespace}:{stream_id}"},
        )
