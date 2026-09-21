from dataclasses import FrozenInstanceError, replace

import pytest

from jmoraIs.gateway_input import UpstreamArtifactReference
from jmoraIs.governed_llm_draft.exact_reference import (
    GovernedLLMDraftReferenceRejected,
    PersistedGovernedLLMDraftReference,
    governed_draft_reference_integrity,
    validate_governed_draft_reference,
)
from tests.test_governed_llm_draft import NOW


def reference(**changes):
    value = PersistedGovernedLLMDraftReference(
        "gdr_" + "a" * 32, "draft-1", "draft-stream-1", 1, None,
        "tenant-test", "invocation-1", "request-1", "correlation-1",
        "pgi_" + "b" * 64,
        UpstreamArtifactReference("AuditDefense", "defense-1", 1, "tenant-test", "c" * 64, "MIP-10.1", "audit_defense"),
        "MIP-10.1", "lifecycle-1", "ACTIVE", "d" * 64, "e" * 64,
        "f" * 64, "governed-llm-draft-provenance:" + "1" * 64, "0" * 64, NOW,
    )
    value = replace(value, integrity_hash=governed_draft_reference_integrity(value))
    if changes:
        value = replace(value, **changes, integrity_hash="0" * 64)
        value = replace(value, integrity_hash=governed_draft_reference_integrity(value))
    return value


def test_reference_is_immutable_metadata_only_and_integrity_protected():
    value = reference()
    assert validate_governed_draft_reference(value)
    assert not {"reviewable_content", "prompt", "raw_response", "provider_payload", "clinical_payload"}.intersection(value.__dict__)
    with pytest.raises(FrozenInstanceError):
        value.draft_version = 2
    assert not validate_governed_draft_reference(replace(value, correlation_id="tampered"))


def test_reference_rejects_inactive_lifecycle_bad_versions_and_hashes():
    with pytest.raises(GovernedLLMDraftReferenceRejected):
        replace(reference(), lifecycle_status="SUPERSEDED")
    with pytest.raises(GovernedLLMDraftReferenceRejected):
        replace(reference(), draft_version=0)
    with pytest.raises(GovernedLLMDraftReferenceRejected):
        replace(reference(), reviewable_content_hash="short")
