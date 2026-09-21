from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from hashlib import sha256
import json

from jmoraIs.gateway_input import UpstreamArtifactReference
from jmoraIs.llm_gateway.exact_reference import PersistedLLMInvocationReference,validate_llm_invocation_reference


class GovernedLLMDraftExactReferenceError(RuntimeError):
    pass


class GovernedLLMDraftReferenceRejected(GovernedLLMDraftExactReferenceError):
    pass


class LegacyMissingPersistedGovernedLLMDraftReference(GovernedLLMDraftReferenceRejected):
    pass


@dataclass(frozen=True)
class PersistedGovernedLLMDraftReference:
    reference_id: str
    draft_id: str
    draft_stream_id: str
    draft_version: int
    predecessor: str | None
    tenant_id: str
    invocation_id: str
    request_id: str
    correlation_id: str
    persisted_gateway_input_id: str
    upstream_artifact_reference: UpstreamArtifactReference
    policy_version: str
    lifecycle_event_id: str
    lifecycle_status: str
    lifecycle_integrity_hash: str
    reviewable_content_hash: str
    draft_integrity_hash: str
    provenance_reference: str
    integrity_hash: str
    issued_at: datetime
    invocation_reference: PersistedLLMInvocationReference | None = None

    def __post_init__(self) -> None:
        required = (
            self.reference_id, self.draft_id, self.draft_stream_id, self.tenant_id,
            self.invocation_id, self.request_id, self.correlation_id,
            self.persisted_gateway_input_id, self.policy_version,
            self.lifecycle_event_id, self.lifecycle_status,
            self.lifecycle_integrity_hash, self.reviewable_content_hash,
            self.draft_integrity_hash, self.provenance_reference, self.integrity_hash,
        )
        if any(not isinstance(value, str) or not value.strip() for value in required):
            raise GovernedLLMDraftReferenceRejected("complete governed draft reference metadata is required")
        if self.draft_version < 1:
            raise GovernedLLMDraftReferenceRejected("canonical draft version must be positive")
        if self.lifecycle_status != "ACTIVE":
            raise GovernedLLMDraftReferenceRejected("only ACTIVE governed drafts can be referenced")
        if any(len(value) != 64 for value in (
            self.lifecycle_integrity_hash, self.reviewable_content_hash,
            self.draft_integrity_hash, self.integrity_hash,
        )):
            raise GovernedLLMDraftReferenceRejected("reference hashes must be SHA-256")
        if self.issued_at.tzinfo is None:
            raise GovernedLLMDraftReferenceRejected("reference timestamp must be timezone-aware")
        upstream = self.upstream_artifact_reference
        if upstream.tenant_id != self.tenant_id or upstream.artifact_version < 1:
            raise GovernedLLMDraftReferenceRejected("upstream artifact reference is inconsistent")
        if self.invocation_reference is not None and (
            not validate_llm_invocation_reference(self.invocation_reference)
            or self.invocation_reference.invocation_id != self.invocation_id
            or self.invocation_reference.tenant_id != self.tenant_id
        ):
            raise GovernedLLMDraftReferenceRejected("typed invocation reference is inconsistent")


def _json_default(value):
    return value.isoformat() if isinstance(value, datetime) else str(value)


def _hash(value) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=_json_default).encode()).hexdigest()


def draft_provenance_reference(draft) -> str:
    return "governed-llm-draft-provenance:" + _hash(list(draft.provenance))


def governed_draft_reference_integrity(reference: PersistedGovernedLLMDraftReference) -> str:
    material = asdict(reference)
    material.pop("integrity_hash")
    if reference.invocation_reference is None:
        material.pop("invocation_reference")
    return _hash(material)


def validate_governed_draft_reference(reference) -> bool:
    return (
        isinstance(reference, PersistedGovernedLLMDraftReference)
        and governed_draft_reference_integrity(reference) == reference.integrity_hash
    )
