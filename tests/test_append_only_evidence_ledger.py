from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone

import pytest

from jmoraIs.evidence_ledger import (
    AppendOnlyEvidenceLedger, LedgerEventType, LedgerIntegrityError, SupportState, hash_payload,
)

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def add(ledger, claim_id, *, source="PubMed", direction="supporting", passage="result", offset=0, **kw):
    return ledger.register_evidence(
        claim_id=claim_id, source_name=source, source_type=source.lower(), passage=passage,
        payload_hash=hash_payload({"source": source, "passage": passage}), retrieved_at=T0,
        verification_version="verify-1", pipeline_version="pipeline-3", policy_version="policy-1",
        support_direction=direction, occurred_at=T0 + timedelta(minutes=offset), **kw,
    )


def ledger_with_claim():
    ledger = AppendOnlyEvidenceLedger()
    claim = ledger.create_claim("Treatment improves outcome", claim_id="claim-1", created_at=T0)
    return ledger, claim


def test_claim_accepts_multiple_sources_and_opposing_evidence():
    ledger, claim = ledger_with_claim()
    _, supporting, _ = add(ledger, claim.claim_id, source="PubMed", direction="supporting", pmid="123")
    _, opposing, _ = add(ledger, claim.claim_id, source="Crossref", direction="opposing", passage="conflict", doi="10.1/x", offset=1)
    snapshot = ledger.reconstruct(claim.claim_id)
    assert {s.support_direction for s in snapshot.active_supports} == {"SUPPORTING", "OPPOSING"}
    assert {s.support_id for s in snapshot.active_supports} == {supporting.support_id, opposing.support_id}


@pytest.mark.parametrize("direction", ["supporting", "opposing", "neutral", "inconclusive"])
def test_all_support_directions_are_supported(direction):
    ledger, claim = ledger_with_claim()
    _, support, _ = add(ledger, claim.claim_id, direction=direction)
    assert support.support_direction == direction.upper()


def test_records_are_frozen_and_hash_chain_detects_tampering():
    ledger, claim = ledger_with_claim()
    fragment, _, _ = add(ledger, claim.claim_id)
    with pytest.raises(FrozenInstanceError):
        fragment.passage = "altered"
    ledger._events[0] = replace(ledger.events[0], reason="tampered")
    with pytest.raises(LedgerIntegrityError):
        ledger.verify_integrity()


def test_reprocessing_is_an_event_without_duplicate_evidence():
    ledger, claim = ledger_with_claim()
    fragment1, support1, _ = add(ledger, claim.claim_id)
    fragment2, support2, event = add(ledger, claim.claim_id, offset=1)
    assert fragment1.fragment_id == fragment2.fragment_id
    assert support1.support_id == support2.support_id
    assert len(ledger.fragments) == len(ledger.supports) == 1
    assert event.event_type == LedgerEventType.REPROCESSING.value
    assert ledger.verify_integrity()


def test_temporal_reconstruction_and_invalidation_preserve_history():
    ledger, claim = ledger_with_claim()
    _, support, _ = add(ledger, claim.claim_id)
    ledger.append_lifecycle_event(claim_id=claim.claim_id, event_type="INVALIDATION", target_support_id=support.support_id, reason="source invalid", occurred_at=T0 + timedelta(minutes=2))
    before = ledger.reconstruct(claim.claim_id, as_of=T0 + timedelta(minutes=1))
    after = ledger.reconstruct(claim.claim_id)
    assert len(before.active_supports) == 1
    assert dict(after.support_states)[support.support_id] == SupportState.INVALIDATED.value
    assert len(after.events) == 2


def test_retraction_is_appended_and_never_erases_original_event():
    ledger, claim = ledger_with_claim()
    _, support, original = add(ledger, claim.claim_id)
    ledger.append_lifecycle_event(claim_id=claim.claim_id, event_type="RETRACTION", target_support_id=support.support_id, reason="publisher retraction", occurred_at=T0 + timedelta(minutes=1))
    snapshot = ledger.reconstruct(claim.claim_id)
    assert snapshot.events[0] == original
    assert dict(snapshot.support_states)[support.support_id] == SupportState.RETRACTED.value


def test_correction_activates_replacement_without_mutating_original():
    ledger, claim = ledger_with_claim()
    _, old, _ = add(ledger, claim.claim_id, passage="old")
    _, new, _ = add(ledger, claim.claim_id, passage="corrected", offset=1)
    ledger.append_lifecycle_event(claim_id=claim.claim_id, event_type="CORRECTION", target_support_id=old.support_id, replacement_support_id=new.support_id, occurred_at=T0 + timedelta(minutes=2))
    states = dict(ledger.reconstruct(claim.claim_id).support_states)
    assert states[old.support_id] == SupportState.CORRECTED.value
    assert states[new.support_id] == SupportState.ACTIVE.value


def test_supersession_is_represented_as_a_new_event():
    ledger, claim = ledger_with_claim()
    _, old, original = add(ledger, claim.claim_id, passage="version 1")
    _, new, _ = add(ledger, claim.claim_id, passage="version 2", offset=1)
    event = ledger.append_lifecycle_event(claim_id=claim.claim_id, event_type="SUPERSESSION", target_support_id=old.support_id, replacement_support_id=new.support_id, reason="new verification", occurred_at=T0 + timedelta(minutes=2))
    snapshot = ledger.reconstruct(claim.claim_id)
    assert snapshot.events[0] == original
    assert event.event_type == LedgerEventType.SUPERSESSION.value
    assert dict(snapshot.support_states)[old.support_id] == SupportState.SUPERSEDED.value


def test_fragment_and_support_hashes_are_reproducible_and_preserve_provenance():
    a, claim_a = ledger_with_claim()
    b, claim_b = ledger_with_claim()
    kwargs = dict(source_locator="https://pubmed/x", exact_location="abstract.results", pmid="123", doi="10.1/x", model_version="none", prompt_version="none")
    fragment_a, support_a, _ = add(a, claim_a.claim_id, **kwargs)
    fragment_b, support_b, _ = add(b, claim_b.claim_id, **kwargs)
    assert fragment_a.fragment_hash == fragment_b.fragment_hash
    assert support_a.support_hash == support_b.support_hash
    assert fragment_a.exact_location == "abstract.results"
    assert (fragment_a.verification_version, fragment_a.pipeline_version, fragment_a.policy_version) == ("verify-1", "pipeline-3", "policy-1")
