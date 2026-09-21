from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from hashlib import sha256
import json

from jmoraIs.gateway_input import UpstreamArtifactReference


class LLMInvocationExactReferenceError(RuntimeError):
    pass


class LLMInvocationReferenceRejected(LLMInvocationExactReferenceError):
    pass


class LegacyMissingPersistedLLMInvocationReference(LLMInvocationReferenceRejected):
    pass


@dataclass(frozen=True)
class PersistedLLMInvocationReference:
    reference_id: str
    invocation_id: str
    request_id: str
    correlation_id: str
    tenant_id: str
    principal_id: str
    purpose: str
    prompt_version_id: str
    prompt_template_id: str
    prompt_version: int
    prompt_hash: str
    persisted_gateway_input_id: str
    upstream_artifact_reference: UpstreamArtifactReference
    provider: str
    model_id: str
    policy_version: str
    output_classification: str
    invocation_status: str
    temperature: float
    seed: int | None
    invocation_integrity_hash: str
    integrity_hash: str
    issued_at: datetime

    def __post_init__(self) -> None:
        required = (
            self.reference_id, self.invocation_id, self.request_id, self.correlation_id,
            self.tenant_id, self.principal_id, self.purpose, self.prompt_version_id,
            self.prompt_template_id, self.prompt_hash, self.persisted_gateway_input_id,
            self.provider, self.model_id, self.policy_version, self.output_classification,
            self.invocation_status, self.invocation_integrity_hash, self.integrity_hash,
        )
        if any(not isinstance(value, str) or not value.strip() for value in required):
            raise LLMInvocationReferenceRejected("complete invocation reference metadata is required")
        if self.prompt_version < 1 or self.upstream_artifact_reference.artifact_version < 1:
            raise LLMInvocationReferenceRejected("canonical reference versions must be positive")
        if self.upstream_artifact_reference.tenant_id != self.tenant_id:
            raise LLMInvocationReferenceRejected("invocation upstream tenant is inconsistent")
        if self.invocation_status not in {"SUCCEEDED", "BLOCKED"}:
            raise LLMInvocationReferenceRejected("only completed invocations can be referenced")
        if self.invocation_status == "BLOCKED" and self.output_classification != "BLOCKED":
            raise LLMInvocationReferenceRejected("blocked invocation classification is inconsistent")
        if self.invocation_status == "SUCCEEDED" and self.output_classification == "BLOCKED":
            raise LLMInvocationReferenceRejected("successful invocation classification is inconsistent")
        if not 0 <= self.temperature <= 2:
            raise LLMInvocationReferenceRejected("invocation temperature is invalid")
        if any(len(value) != 64 for value in (
            self.prompt_hash, self.invocation_integrity_hash, self.integrity_hash,
        )):
            raise LLMInvocationReferenceRejected("reference hashes must be SHA-256")
        if self.issued_at.tzinfo is None:
            raise LLMInvocationReferenceRejected("reference timestamp must be timezone-aware")


def _json_default(value):
    return value.value if hasattr(value, "value") else value.isoformat() if isinstance(value, datetime) else str(value)


def _hash(value) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=_json_default).encode()).hexdigest()


def llm_invocation_integrity_hash(invocation) -> str:
    return _hash(asdict(invocation))


def llm_invocation_reference_integrity(reference: PersistedLLMInvocationReference) -> str:
    material = asdict(reference)
    material.pop("integrity_hash")
    return _hash(material)


def validate_llm_invocation_reference(reference) -> bool:
    return (
        isinstance(reference, PersistedLLMInvocationReference)
        and llm_invocation_reference_integrity(reference) == reference.integrity_hash
    )
