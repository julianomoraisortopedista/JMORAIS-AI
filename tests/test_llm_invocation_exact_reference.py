from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone

import pytest

from jmoraIs.gateway_input import UpstreamArtifactReference
from jmoraIs.llm_gateway.exact_reference import (
    LLMInvocationReferenceRejected,
    PersistedLLMInvocationReference,
    llm_invocation_reference_integrity,
    validate_llm_invocation_reference,
)


NOW = datetime(2026, 9, 5, tzinfo=timezone.utc)


def reference(**changes):
    value = PersistedLLMInvocationReference(
        "lir_" + "a" * 32, "invocation-1", "request-1", "correlation-1",
        "tenant-1", "principal-1", "CLINICAL_VALIDATION", "prompt-version-1",
        "prompt-template-1", 1, "b" * 64, "pgi_" + "c" * 64,
        UpstreamArtifactReference("AuditDefense", "defense-1", 1, "tenant-1", "d" * 64, "MIP-10.1", "audit_defense"),
        "MOCK", "model-1", "MIP-10.1", "APPROVED_FOR_REVIEW", "SUCCEEDED",
        0.0, 7, "e" * 64, "0" * 64, NOW,
    )
    value = replace(value, integrity_hash=llm_invocation_reference_integrity(value))
    if changes:
        value = replace(value, **changes, integrity_hash="0" * 64)
        value = replace(value, integrity_hash=llm_invocation_reference_integrity(value))
    return value


def test_invocation_reference_is_immutable_metadata_only_and_integrity_protected():
    value = reference()
    assert validate_llm_invocation_reference(value)
    assert not {"output_text", "prompt", "raw_response", "provider_payload", "clinical_payload"}.intersection(value.__dict__)
    with pytest.raises(FrozenInstanceError):
        value.invocation_id = "changed"
    assert not validate_llm_invocation_reference(replace(value, request_id="tampered"))


def test_invocation_reference_fails_closed_for_invalid_state_and_linkage():
    with pytest.raises(LLMInvocationReferenceRejected):
        reference(invocation_status="FAILED")
    with pytest.raises(LLMInvocationReferenceRejected):
        reference(invocation_status="BLOCKED")
    with pytest.raises(LLMInvocationReferenceRejected):
        reference(prompt_version=0)
    with pytest.raises(LLMInvocationReferenceRejected):
        reference(prompt_hash="short")
    with pytest.raises(LLMInvocationReferenceRejected):
        reference(upstream_artifact_reference=replace(reference().upstream_artifact_reference, tenant_id="other"))
