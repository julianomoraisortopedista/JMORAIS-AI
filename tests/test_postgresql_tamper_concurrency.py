from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from jmoraIs.appraisal.governed import GovernedEvidence
from jmoraIs.appraisal.persistence import SQLAlchemyGovernedEvidenceRepository
from jmoraIs.clinical.governance_persistence import (
    SQLAlchemyGovernedDecisionAuditRepository,
    SQLAlchemyGovernedEvidenceLifecycleRepository,
)
from jmoraIs.clinical.governed import _event
from jmoraIs.clinical.review_governance import (
    GovernedEvidenceLifecycleEvent, GovernedEvidenceLifecycleStatus,
)
from jmoraIs.infrastructure.database_invariants import ConcurrencyConflict


pytestmark = pytest.mark.integration
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


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
    engine.dispose()


def evidence(package_id: str, identifier: str | None = None) -> GovernedEvidence:
    return GovernedEvidence(
        identifier or uuid4().hex, package_id, "appraisal", "RANDOMIZED_CONTROLLED_TRIAL",
        "HIGH", 0.9, "STRONG_FOR", ("ADULT",), "authority", "VALID", None, None,
        None, (), ("SUPPORTING",), ("provenance",), ("ledger",), "policy", "appraisal",
        (), NOW, uuid4().hex,
    )


def seed_package(engine, package_id: str) -> None:
    with engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO evidence_package_catalog
                (package_id, package_payload, association_payload, recorded_at)
            VALUES (:id, CAST(:package AS jsonb), CAST(:association AS jsonb), :now)
        """), {"id": package_id, "package": "{}", "association": "{}", "now": NOW})


def seed_governed_evidence(engine, identifier: str) -> None:
    package_id = f"package-{uuid4().hex}"
    seed_package(engine, package_id)
    SQLAlchemyGovernedEvidenceRepository(engine).append(evidence(package_id, identifier))


def lifecycle(identifier: str, previous: str | None = None) -> GovernedEvidenceLifecycleEvent:
    return GovernedEvidenceLifecycleEvent(
        uuid4().hex, identifier, GovernedEvidenceLifecycleStatus.ACTIVE, (), NOW,
        "test", "policy", previous, uuid4().hex,
    )


def test_postgresql_rejects_update_delete_duplicate_version_and_foreign_key(postgres_engine):
    package_id = f"pg-{uuid4().hex}"
    seed_package(postgres_engine, package_id)
    repository = SQLAlchemyGovernedEvidenceRepository(postgres_engine)
    repository.append(evidence(package_id))

    with pytest.raises(DBAPIError), postgres_engine.begin() as connection:
        connection.execute(text(
            "UPDATE governed_evidence_versions SET integrity_hash = :hash "
            "WHERE evidence_package_id = :package"
        ), {"hash": "tampered", "package": package_id})
    with pytest.raises(DBAPIError), postgres_engine.begin() as connection:
        connection.execute(text(
            "DELETE FROM governed_evidence_versions WHERE evidence_package_id = :package"
        ), {"package": package_id})
    with pytest.raises(IntegrityError), postgres_engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO governed_evidence_versions
                (governed_evidence_id, evidence_package_id, stream_version, integrity_hash, issued_at, payload)
            VALUES (:id, :package, 1, :hash, :issued, CAST(:payload AS json))
        """), {"id": uuid4().hex, "package": package_id, "hash": uuid4().hex,
               "issued": NOW, "payload": "{}"})
    with pytest.raises(IntegrityError), postgres_engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO evidence_package_versions
                (package_id, package_version, integrity_hash, recorded_at)
            VALUES (:id, '1', :hash, :now)
        """), {"id": f"absent-{uuid4().hex}", "hash": uuid4().hex, "now": NOW})


def test_concurrent_governed_versions_are_unique_and_recover_after_restart(postgres_engine):
    package_id = f"concurrent-{uuid4().hex}"
    seed_package(postgres_engine, package_id)
    items = (evidence(package_id), evidence(package_id))

    def append(item):
        SQLAlchemyGovernedEvidenceRepository(postgres_engine).append(item)

    with ThreadPoolExecutor(max_workers=2) as pool:
        tuple(pool.map(append, items, timeout=10))

    restarted = SQLAlchemyGovernedEvidenceRepository(postgres_engine)
    history = restarted.version_history(package_id)
    assert {item.governed_evidence_id for item in history} == {
        item.governed_evidence_id for item in items
    }
    with postgres_engine.connect() as connection:
        versions = connection.execute(text(
            "SELECT stream_version FROM governed_evidence_versions "
            "WHERE evidence_package_id=:id ORDER BY stream_version"
        ), {"id": package_id}).scalars().all()
    assert versions == [1, 2]


def test_concurrent_audit_append_is_fail_closed_then_retryable(postgres_engine):
    case_id = f"case-{uuid4().hex}"
    first = _event(case_id, "TEST", NOW, (), (), (), (), (), None, "PENDING_REVIEW",
                   None, None, "policy", None, None)
    second = _event(case_id, "TEST", NOW, (), (), (), (), (), None, "PENDING_REVIEW",
                    None, None, "policy", None, None)

    def append(item):
        SQLAlchemyGovernedDecisionAuditRepository(postgres_engine).append(item)

    results = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(append, item) for item in (first, second)]
        for future in futures:
            try:
                future.result(timeout=10)
                results.append("committed")
            except ConcurrencyConflict:
                results.append("retry")
    assert sorted(results) == ["committed", "retry"]

    repository = SQLAlchemyGovernedDecisionAuditRepository(postgres_engine)
    current = repository.history(case_id)[-1]
    retry = _event(case_id, "TEST_RETRY", NOW, (), (), (), (), (), None, "PENDING_REVIEW",
                   None, None, "policy", None, current.event_hash)
    repository.append(retry)
    replayed = SQLAlchemyGovernedDecisionAuditRepository(postgres_engine).history(case_id)
    assert len(replayed) == 2
    assert replayed[1].previous_event_hash == replayed[0].event_hash


def test_lifecycle_stream_rejects_invalid_hash_and_duplicate_position(postgres_engine):
    identifier = f"governed-{uuid4().hex}"
    seed_governed_evidence(postgres_engine, identifier)
    repository = SQLAlchemyGovernedEvidenceLifecycleRepository(postgres_engine)
    first = lifecycle(identifier)
    repository.append(first)

    with pytest.raises(ConcurrencyConflict):
        repository.append(lifecycle(identifier, previous="0" * 64))

    with pytest.raises(DBAPIError), postgres_engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO governed_evidence_lifecycle_events
                (event_id, governed_evidence_id, stream_position, previous_event_hash,
                 event_hash, occurred_at, payload)
            VALUES (:event, :owner, 2, :previous, :hash, :now, CAST(:payload AS json))
        """), {"event": uuid4().hex, "owner": identifier, "previous": "bad",
               "hash": uuid4().hex, "now": NOW, "payload": "{}"})
    assert SQLAlchemyGovernedEvidenceLifecycleRepository(postgres_engine).history(identifier) == (first,)


def test_concurrent_lifecycle_appends_are_ordered_with_controlled_retry(postgres_engine):
    identifier = f"lifecycle-concurrent-{uuid4().hex}"
    seed_governed_evidence(postgres_engine, identifier)
    candidates = (lifecycle(identifier), lifecycle(identifier))

    def append(item):
        SQLAlchemyGovernedEvidenceLifecycleRepository(postgres_engine).append(item)

    outcomes = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(append, item) for item in candidates]
        for future in futures:
            try:
                future.result(timeout=10)
                outcomes.append("committed")
            except ConcurrencyConflict:
                outcomes.append("retry")
    assert sorted(outcomes) == ["committed", "retry"]

    repository = SQLAlchemyGovernedEvidenceLifecycleRepository(postgres_engine)
    first = repository.history(identifier)[0]
    repository.append(lifecycle(identifier, first.event_hash))
    history = repository.history(identifier)
    assert history[1].previous_event_hash == history[0].event_hash
    with postgres_engine.connect() as connection:
        positions = connection.execute(text(
            "SELECT stream_position FROM governed_evidence_lifecycle_events "
            "WHERE governed_evidence_id=:id ORDER BY stream_position"
        ), {"id": identifier}).scalars().all()
    assert positions == [1, 2]
