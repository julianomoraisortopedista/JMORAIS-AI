from copy import deepcopy
from datetime import datetime, timezone

import jmoraIs.infrastructure.cryptographic_replay as replay_module
from jmoraIs.infrastructure.cryptographic_replay import (
    PostgreSQLCryptographicReplayEngine,
    ReplayIntegrityStatus,
)


NOW = "2026-08-13T12:00:00+00:00"


def definition(kind):
    return next(item for item in replay_module._MANDATORY_TRUST_STREAMS if item.kind == kind)


def fixture(kind):
    common = {"tenant_id": "tenant-1", "occurred_at": NOW, "stream_position": 1,
              "previous_hash": None, "integrity_hash": ""}
    if kind == "draft_lifecycle":
        payload = {**common, "lifecycle_event_id": "life-1", "draft_id": "draft-1",
                   "draft_version": 1, "prior_status": None, "resulting_status": "ACTIVE",
                   "reason_reference": "ISSUED", "actor_reference": "issuer",
                   "policy_version": "P1", "predecessor_event_id": None}
    elif kind == "human_review":
        payload = {**common, "review_event_id": "review-1", "draft_id": "draft-1",
                   "draft_version": 1, "invocation_id": "inv-1", "request_id": "req-1",
                   "correlation_id": "corr-1", "organization_id": "org-1",
                   "prior_state": "PENDING_REVIEW", "resulting_state": "APPROVED_BY_REVIEWER",
                   "decision": "APPROVE", "reviewer_id": "reviewer-1", "reviewer_role": "REVIEWER",
                   "policy_version": "P1", "predecessor_event_id": None}
    else:
        payload = {**common, "event_id": "security-1", "event_type": "REVIEW_ATTEMPT",
                   "draft_id": "draft-1", "draft_version": 1, "invocation_id": "inv-1",
                   "request_id": "req-1", "correlation_id": "corr-1",
                   "principal_id": "principal-1", "reviewer_id": "reviewer-1",
                   "reviewer_role": "REVIEWER", "organization_id": "org-1",
                   "result": "SUCCESS", "reason_code": "POLICY_ACCEPTED", "policy_version": "P1"}
    event_hash = replay_module._hash(payload)
    payload["integrity_hash"] = event_hash
    owner = payload[definition(kind).owner]
    row = {"event_id": payload[definition(kind).event_id], "owner_id": owner,
           "tenant_id": "tenant-1", "stream_position": 1, "previous_event_hash": None,
           "event_hash": event_hash, "occurred_at": datetime.fromisoformat(NOW),
           "payload": deepcopy(payload), "persisted_row": deepcopy(payload)}
    context = ({"draft-1": {"draft_id": "draft-1", "version": 1, "invocation_id": "inv-1",
                              "request_id": "req-1", "correlation_id": "corr-1", "tenant_id": "tenant-1"}},
               {"inv-1"}, {"req-1"})
    checkpoint = {"stream_position": 1, "head_hash": event_hash}
    return payload, row, context, checkpoint, owner


def verify(kind, rows, context, checkpoint, owner):
    engine = object.__new__(PostgreSQLCryptographicReplayEngine)
    return engine._verify_trust_rows(definition(kind), "tenant-1", owner, rows, context, checkpoint)


def reasons(report):
    return {reason for failure in report.failed_events for reason in failure.reasons}


def test_every_persisted_domain_column_is_covered_by_row_payload_verification():
    for kind in ("draft_lifecycle", "human_review", "review_security"):
        _, row, context, checkpoint, owner = fixture(kind)
        assert verify(kind, (row,), context, checkpoint, owner).integrity_status is ReplayIntegrityStatus.VALID
        for field in replay_module._TRUST_ROW_FIELDS[kind]:
            changed = deepcopy(row)
            changed["persisted_row"][field] = "tampered"
            report = verify(kind, (changed,), context, checkpoint, owner)
            assert report.integrity_status is ReplayIntegrityStatus.TAMPERED
            assert "ROW_PAYLOAD_IDENTITY_MISMATCH" in reasons(report)


def test_every_persisted_domain_payload_change_requires_hash_recomputation():
    for kind in ("draft_lifecycle", "human_review", "review_security"):
        _, row, context, checkpoint, owner = fixture(kind)
        for field in replay_module._TRUST_ROW_FIELDS[kind]:
            changed = deepcopy(row)
            changed["payload"][field] = "tampered"
            report = verify(kind, (changed,), context, checkpoint, owner)
            assert report.integrity_status is ReplayIntegrityStatus.TAMPERED
            assert "MODIFIED_PAYLOAD" in reasons(report)


def test_stage14_stream_structure_completeness_duplicates_and_references_fail_closed():
    for kind in ("draft_lifecycle", "human_review", "review_security"):
        _, row, context, checkpoint, owner = fixture(kind)
        assert "STREAM_COMPLETENESS_FAILURE" in reasons(verify(kind, (), context, checkpoint, owner))
        changed = deepcopy(row); changed["stream_position"] = 2
        assert "BROKEN_STREAM_POSITION" in reasons(verify(kind, (changed,), context, checkpoint, owner))
        duplicate = deepcopy(row); duplicate["stream_position"] = 2
        duplicate_checkpoint = {"stream_position": 2, "head_hash": duplicate["event_hash"]}
        assert "DUPLICATE_EVENT" in reasons(verify(kind, (row, duplicate), context, duplicate_checkpoint, owner))
        missing_references = ({}, set(), set())
        assert "INCONSISTENT_PROVENANCE_REFERENCES" in reasons(verify(kind, (row,), missing_references, checkpoint, owner))


def test_security_stream_reordering_timestamp_and_checkpoint_mismatch_fail_closed():
    _, first, context, _, owner = fixture("review_security")
    second = deepcopy(first)
    second["event_id"] = second["payload"]["event_id"] = "security-2"
    second["stream_position"] = second["payload"]["stream_position"] = 2
    second["previous_event_hash"] = second["payload"]["previous_hash"] = first["event_hash"]
    second["occurred_at"] = datetime(2026, 8, 12, tzinfo=timezone.utc)
    second["payload"]["occurred_at"] = "2026-08-12T00:00:00+00:00"
    canonical = deepcopy(second["payload"]); canonical["integrity_hash"] = ""
    second["event_hash"] = second["payload"]["integrity_hash"] = replay_module._hash(canonical)
    report = verify("review_security", (first, second), context,
                    {"stream_position": 2, "head_hash": second["event_hash"]}, owner)
    assert "INVALID_TIMESTAMP_ORDER" in reasons(report)
    report = verify("review_security", (first,), context,
                    {"stream_position": 99, "head_hash": "0" * 64}, owner)
    assert "STREAM_COMPLETENESS_FAILURE" in reasons(report)
