from dataclasses import FrozenInstanceError,replace
from datetime import datetime,timezone
import pytest
from jmoraIs.llm_human_review.exact_reference import *
from tests.test_governed_llm_draft_exact_reference import reference as draft_reference
NOW=datetime(2026,9,6,tzinfo=timezone.utc)
def reference(**changes):
    value=PersistedHumanReviewReference("hrr_"+"a"*32,"review-1",draft_reference(),1,"tenant-test","reviewer-1","REVIEWER","APPROVE","APPROVED_BY_REVIEWER","ST-15.1","request-1","correlation-1",None,None,"b"*64,"0"*64,NOW)
    value=replace(value,integrity_hash=human_review_reference_integrity(value))
    if changes:value=replace(value,**changes,integrity_hash="0"*64);value=replace(value,integrity_hash=human_review_reference_integrity(value))
    return value
def test_reference_is_immutable_metadata_only_and_integrity_protected():
    value=reference();assert validate_human_review_reference(value)
    assert not {"draft_content","clinical_payload","prompt","llm_response","jwt","jti"}.intersection(value.__dict__)
    with pytest.raises(FrozenInstanceError):value.stream_position=2
    assert not validate_human_review_reference(replace(value,reviewer_id="tampered"))
def test_reference_rejects_invalid_position_hash_and_draft():
    with pytest.raises(HumanReviewReferenceRejected):reference(stream_position=0)
    with pytest.raises(HumanReviewReferenceRejected):reference(event_integrity_hash="short")
    with pytest.raises(HumanReviewReferenceRejected):reference(tenant_id="other")
