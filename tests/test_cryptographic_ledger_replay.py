from __future__ import annotations

import os
import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

from jmoraIs.infrastructure.cryptographic_replay import (
    PostgreSQLCryptographicReplayEngine, ReplayIntegrityStatus,
)
from jmoraIs.evidence_ledger import AppendOnlyEvidenceLedger


pytestmark = pytest.mark.integration
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
TABLE = "canonical_ledger_events"


@pytest.fixture(scope="module")
def postgres_engine():
    url = os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    from alembic import command
    from alembic.config import Config
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    engine = create_engine(url, future=True, pool_pre_ping=True)
    yield engine
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    engine.dispose()


def stream(engine, size: int = 3) -> str:
    claim_id = uuid4().hex
    ledger = AppendOnlyEvidenceLedger()
    ledger.create_claim(f"Replay claim {claim_id}", claim_id=claim_id, created_at=NOW)
    for index in range(size):
        ledger.register_evidence(
            claim_id=claim_id, source_name="PubMed", source_type="pubmed",
            passage=f"Evidence passage {claim_id} {index}",
            payload_hash=f"{claim_id}{index}".encode().hex()[:64].ljust(64, "0"),
            retrieved_at=NOW + timedelta(seconds=index), verification_version="ST-21",
            pipeline_version="ST-21", policy_version="ST-21",
            support_direction="supporting", pmid=str(10000000 + index),
            occurred_at=NOW + timedelta(seconds=index),
        )
    def payload(item):
        values = asdict(item)
        for key, value in tuple(values.items()):
            if isinstance(value, datetime):
                values[key] = value.isoformat()
        return json.dumps(values, sort_keys=True)

    with engine.begin() as connection:
        claim = ledger.claims[0]
        connection.execute(text("""
            INSERT INTO canonical_ledger_claims (claim_id, payload)
            VALUES (:id, CAST(:payload AS jsonb))
        """), {"id": claim.claim_id, "payload": payload(claim)})
        for fragment in ledger.fragments:
            connection.execute(text("""
                INSERT INTO canonical_ledger_fragments (fragment_id, payload)
                VALUES (:id, CAST(:payload AS jsonb))
            """), {"id": fragment.fragment_id, "payload": payload(fragment)})
        for support in ledger.supports:
            connection.execute(text("""
                INSERT INTO canonical_ledger_supports (support_id, claim_id, payload)
                VALUES (:id, :claim, CAST(:payload AS jsonb))
            """), {"id": support.support_id, "claim": claim_id, "payload": payload(support)})
        for position, event in enumerate(ledger.events, 1):
            connection.execute(text("""
                INSERT INTO canonical_ledger_events
                    (event_id, claim_id, stream_position, previous_event_hash,
                     event_hash, occurred_at, payload)
                VALUES (:id, :claim, :position, :previous, :hash, :occurred, CAST(:payload AS jsonb))
            """), {"id": event.event_id, "claim": claim_id, "position": position,
                   "previous": event.previous_event_hash, "hash": event.event_hash,
                   "occurred": event.occurred_at, "payload": payload(event)})
    return claim_id


def tamper(engine, statements: tuple[tuple[str, dict], ...]) -> None:
    with engine.begin() as connection:
        connection.execute(text(f"ALTER TABLE {TABLE} DISABLE TRIGGER ALL"))
        try:
            for sql, parameters in statements:
                connection.execute(text(sql), parameters)
        finally:
            connection.execute(text(f"ALTER TABLE {TABLE} ENABLE TRIGGER ALL"))


def reasons(report) -> set[str]:
    return {reason for failure in report.failed_events for reason in failure.reasons}


def test_full_replay_from_genesis_is_valid_and_structured(postgres_engine):
    claim_id = stream(postgres_engine, 4)
    report = PostgreSQLCryptographicReplayEngine(postgres_engine).replay_stream(TABLE, claim_id)
    assert report.integrity_status == ReplayIntegrityStatus.VALID
    assert len(report.verified_events) == 4
    assert report.failed_events == ()
    assert report.broken_chains == ()
    assert report.tampered_events == ()


def test_modified_payload_is_detected_after_restart(postgres_engine):
    claim_id = stream(postgres_engine)
    tamper(postgres_engine, ((
        f"UPDATE {TABLE} SET payload=jsonb_set(payload, '{{reason}}', '" + '"tampered"' + "'::jsonb) "
        "WHERE claim_id=:claim AND stream_position=2",
        {"claim": claim_id},
    ),))
    restarted = PostgreSQLCryptographicReplayEngine(postgres_engine)
    report = restarted.replay_stream(TABLE, claim_id)
    assert report.integrity_status == ReplayIntegrityStatus.TAMPERED
    assert "MODIFIED_PAYLOAD" in reasons(report)


def test_removed_event_and_missing_position_are_detected(postgres_engine):
    claim_id = stream(postgres_engine, 4)
    tamper(postgres_engine, ((
        f"DELETE FROM {TABLE} WHERE claim_id=:claim AND stream_position=2",
        {"claim": claim_id},
    ),))
    report = PostgreSQLCryptographicReplayEngine(postgres_engine).replay_stream(TABLE, claim_id)
    assert report.integrity_status == ReplayIntegrityStatus.TAMPERED
    assert "BROKEN_STREAM_POSITION" in reasons(report)
    assert "BROKEN_PREVIOUS_HASH" in reasons(report)


def test_removed_tail_is_detected_by_independent_checkpoint(postgres_engine):
    claim_id = stream(postgres_engine, 3)
    tamper(postgres_engine, ((
        f"DELETE FROM {TABLE} WHERE claim_id=:claim AND stream_position=3",
        {"claim": claim_id},
    ),))
    report = PostgreSQLCryptographicReplayEngine(postgres_engine).replay_stream(TABLE, claim_id)
    assert report.integrity_status == ReplayIntegrityStatus.TAMPERED
    assert "STREAM_COMPLETENESS_FAILURE" in reasons(report)


def test_inserted_duplicate_event_is_detected(postgres_engine):
    claim_id = stream(postgres_engine, 2)
    inserted_id, inserted_hash = uuid4().hex, uuid4().hex
    tamper(postgres_engine, ((f"""
        INSERT INTO {TABLE}
            (event_id, claim_id, stream_position, previous_event_hash, event_hash, occurred_at, payload)
        SELECT :event_id, claim_id, 3, event_hash, :event_hash, occurred_at + interval '1 second', payload
          FROM {TABLE} WHERE claim_id=:claim AND stream_position=2
    """, {"claim": claim_id, "event_id": inserted_id, "event_hash": inserted_hash}),))
    report = PostgreSQLCryptographicReplayEngine(postgres_engine).replay_stream(TABLE, claim_id)
    assert report.integrity_status == ReplayIntegrityStatus.TAMPERED
    assert "DUPLICATE_EVENT" in reasons(report)
    assert "ROW_PAYLOAD_IDENTITY_MISMATCH" in reasons(report)


def test_reordered_events_and_invalid_timestamp_are_detected(postgres_engine):
    claim_id = stream(postgres_engine, 3)
    tamper(postgres_engine, (
        (f"UPDATE {TABLE} SET stream_position=100 WHERE claim_id=:claim AND stream_position=2", {"claim": claim_id}),
        (f"UPDATE {TABLE} SET stream_position=2 WHERE claim_id=:claim AND stream_position=3", {"claim": claim_id}),
        (f"UPDATE {TABLE} SET stream_position=3 WHERE claim_id=:claim AND stream_position=100", {"claim": claim_id}),
        (f"UPDATE {TABLE} SET occurred_at=:time, payload=jsonb_set(payload, '{{occurred_at}}', to_jsonb(CAST(:iso AS text))) WHERE claim_id=:claim AND stream_position=3",
         {"claim": claim_id, "time": NOW - timedelta(days=1), "iso": (NOW - timedelta(days=1)).isoformat()}),
    ))
    report = PostgreSQLCryptographicReplayEngine(postgres_engine).replay_stream(TABLE, claim_id)
    assert report.integrity_status == ReplayIntegrityStatus.TAMPERED
    assert "BROKEN_PREVIOUS_HASH" in reasons(report)
    assert "INVALID_TIMESTAMP_ORDER" in reasons(report)


def test_modified_previous_hash_is_detected(postgres_engine):
    claim_id = stream(postgres_engine)
    tamper(postgres_engine, ((
        f"UPDATE {TABLE} SET previous_event_hash=:hash WHERE claim_id=:claim AND stream_position=2",
        {"claim": claim_id, "hash": "0" * 64},
    ),))
    report = PostgreSQLCryptographicReplayEngine(postgres_engine).replay_stream(TABLE, claim_id)
    assert report.integrity_status == ReplayIntegrityStatus.TAMPERED
    assert "BROKEN_PREVIOUS_HASH" in reasons(report)


def test_multiple_streams_restart_and_large_history_replay(postgres_engine):
    first = stream(postgres_engine, 10)
    second = stream(postgres_engine, 500)
    restarted = PostgreSQLCryptographicReplayEngine(postgres_engine)
    first_report = restarted.replay_stream(TABLE, first)
    second_report = restarted.replay_stream(TABLE, second)
    assert first_report.integrity_status == ReplayIntegrityStatus.VALID
    assert second_report.integrity_status == ReplayIntegrityStatus.VALID
    assert len(second_report.verified_events) == 500
    overall = restarted.replay_all()
    assert overall.streams
    assert overall.integrity_status == ReplayIntegrityStatus.TAMPERED  # prior intentionally corrupted streams
    assert overall.overall_decision == ReplayIntegrityStatus.TAMPERED
