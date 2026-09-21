from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import text

from jmoraIs.gateway_input import persisted_gateway_input_integrity_hash
from jmoraIs.llm_gateway.exact_reference import (
    LegacyMissingPersistedLLMInvocationReference,
    PersistedLLMInvocationReference,
)
from jmoraIs.tenancy.context import current_tenant_context

from .application import validate_draft_integrity
from .domain import GovernedLLMDraft, GovernedLLMDraftLifecycleStatus
from .exact_reference import (
    GovernedLLMDraftReferenceRejected,
    LegacyMissingPersistedGovernedLLMDraftReference,
    PersistedGovernedLLMDraftReference,
    draft_provenance_reference,
    governed_draft_reference_integrity,
    validate_governed_draft_reference,
)
from .lifecycle import validate_lifecycle_chain
from .persistence import GovernedLLMDraftJsonCodec


class PostgreSQLGovernedLLMDraftExactReferenceRepository:
    """Owner-side exact reference store; compatibility scalar reads never enter this boundary."""

    def __init__(self, engine, draft_attestor, *, invocation_references=None, clock=None, codec=None):
        if engine.dialect.name != "postgresql":
            raise ValueError("governed draft exact references require PostgreSQL")
        self._engine = engine
        self._draft_attestor = draft_attestor
        self._invocation_references = invocation_references
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._codec = codec or GovernedLLMDraftJsonCodec()

    def reference_for(
        self,
        draft: GovernedLLMDraft,
        invocation_reference: PersistedLLMInvocationReference | None = None,
    ) -> PersistedGovernedLLMDraftReference:
        if not isinstance(draft, GovernedLLMDraft):
            raise GovernedLLMDraftReferenceRejected("typed GovernedLLMDraft is required")
        if self._invocation_references is None or invocation_reference is None:
            raise LegacyMissingPersistedLLMInvocationReference(
                "LEGACY_MISSING_PERSISTED_LLM_INVOCATION_REFERENCE"
            )
        exact_invocation = self._invocation_references.get_exact(invocation_reference)
        tenant = current_tenant_context()
        canonical, invocation, gateway, lifecycle = self._validate_exact(draft.draft_id)
        if canonical != draft:
            raise GovernedLLMDraftReferenceRejected("draft does not match canonical persistence")
        if tenant.tenant_id != draft.tenant_id or tenant.policy_version != draft.policy_version:
            raise GovernedLLMDraftReferenceRejected("draft tenant or policy mismatch")
        if exact_invocation.invocation_id != draft.invocation_id:
            raise GovernedLLMDraftReferenceRejected("draft invocation reference mismatch")
        issued_at = self._clock()
        unsigned = PersistedGovernedLLMDraftReference(
            "gdr_" + uuid4().hex, draft.draft_id, draft.draft_stream_id, draft.version,
            draft.predecessor, draft.tenant_id, draft.invocation_id, draft.request_id,
            draft.correlation_id, invocation["persisted_gateway_input_id"],
            draft.upstream_artifact_reference, draft.policy_version,
            lifecycle.lifecycle_event_id, lifecycle.resulting_status.value,
            lifecycle.integrity_hash, draft.reviewable_content_hash,
            draft.integrity_hash, draft_provenance_reference(draft), "0" * 64, issued_at,
            invocation_reference,
        )
        reference = replace(unsigned, integrity_hash=governed_draft_reference_integrity(unsigned))
        upstream = reference.upstream_artifact_reference
        with self._engine.begin() as connection:
            connection.execute(text("""INSERT INTO governed_llm_draft_persisted_references
              (reference_id,draft_id,draft_stream_id,draft_version,predecessor,tenant_id,
               invocation_id,request_id,correlation_id,persisted_gateway_input_id,
               upstream_artifact_type,upstream_artifact_id,upstream_artifact_version,
               upstream_integrity_reference,upstream_policy_version,upstream_source_context,
               policy_version,lifecycle_event_id,lifecycle_status,lifecycle_integrity_hash,
               reviewable_content_hash,draft_integrity_hash,provenance_reference,integrity_hash,issued_at,
               invocation_reference_id,invocation_reference_integrity_hash)
              VALUES(:reference,:draft,:stream,:version,:predecessor,:tenant,:invocation,:request,
               :correlation,:gateway,:upstream_type,:upstream_id,:upstream_version,
               :upstream_integrity,:upstream_policy,:upstream_source,:policy,:lifecycle,:status,
               :lifecycle_hash,:content_hash,:draft_hash,:provenance,:integrity,:issued,
               :invocation_reference_id,:invocation_reference_integrity_hash)"""), {
                "reference": reference.reference_id, "draft": reference.draft_id,
                "stream": reference.draft_stream_id, "version": reference.draft_version,
                "predecessor": reference.predecessor, "tenant": reference.tenant_id,
                "invocation": reference.invocation_id, "request": reference.request_id,
                "correlation": reference.correlation_id,
                "gateway": reference.persisted_gateway_input_id,
                "upstream_type": upstream.artifact_type, "upstream_id": upstream.artifact_id,
                "upstream_version": upstream.artifact_version,
                "upstream_integrity": upstream.integrity_reference,
                "upstream_policy": upstream.policy_version,
                "upstream_source": upstream.source_context,
                "policy": reference.policy_version, "lifecycle": reference.lifecycle_event_id,
                "status": reference.lifecycle_status,
                "lifecycle_hash": reference.lifecycle_integrity_hash,
                "content_hash": reference.reviewable_content_hash,
                "draft_hash": reference.draft_integrity_hash,
                "provenance": reference.provenance_reference,
                "integrity": reference.integrity_hash, "issued": reference.issued_at,
                "invocation_reference_id": invocation_reference.reference_id,
                "invocation_reference_integrity_hash": invocation_reference.integrity_hash,
            })
        return reference

    def get_exact(self, reference: PersistedGovernedLLMDraftReference) -> GovernedLLMDraft:
        if not validate_governed_draft_reference(reference):
            raise GovernedLLMDraftReferenceRejected("authentic owner-issued governed draft reference is required")
        tenant = current_tenant_context()
        if reference.tenant_id != tenant.tenant_id or reference.policy_version != tenant.policy_version:
            raise GovernedLLMDraftReferenceRejected("governed draft tenant or policy mismatch")
        with self._engine.connect() as connection:
            row = connection.execute(text(
                "SELECT * FROM governed_llm_draft_persisted_references WHERE reference_id=:id"
            ), {"id": reference.reference_id}).mappings().first()
        if row is None:
            raise LegacyMissingPersistedGovernedLLMDraftReference(
                "LEGACY_MISSING_PERSISTED_GOVERNED_LLM_DRAFT_REFERENCE"
            )
        invocation_reference = self._load_invocation_reference(row)
        persisted = self._decode_reference(row, invocation_reference)
        if persisted != reference:
            raise GovernedLLMDraftReferenceRejected("persisted governed draft reference is inconsistent")
        draft, invocation, gateway, lifecycle = self._validate_exact(reference.draft_id)
        exact_invocation = self._invocation_references.get_exact(reference.invocation_reference)
        if exact_invocation.invocation_id != invocation["invocation_id"]:
            raise GovernedLLMDraftReferenceRejected("persisted invocation reference linkage mismatch")
        actual = (
            draft.draft_id, draft.draft_stream_id, draft.version, draft.predecessor,
            draft.tenant_id, draft.invocation_id, draft.request_id, draft.correlation_id,
            invocation["persisted_gateway_input_id"], draft.upstream_artifact_reference,
            draft.policy_version, lifecycle.lifecycle_event_id,
            lifecycle.resulting_status.value, lifecycle.integrity_hash,
            draft.reviewable_content_hash, draft.integrity_hash,
            draft_provenance_reference(draft),
        )
        expected = (
            reference.draft_id, reference.draft_stream_id, reference.draft_version,
            reference.predecessor, reference.tenant_id, reference.invocation_id,
            reference.request_id, reference.correlation_id,
            reference.persisted_gateway_input_id, reference.upstream_artifact_reference,
            reference.policy_version, reference.lifecycle_event_id,
            reference.lifecycle_status, reference.lifecycle_integrity_hash,
            reference.reviewable_content_hash, reference.draft_integrity_hash,
            reference.provenance_reference,
        )
        if actual != expected or gateway.persisted_gateway_input_id != reference.persisted_gateway_input_id:
            raise GovernedLLMDraftReferenceRejected("governed draft reference linkage mismatch")
        return draft

    def _load_invocation_reference(self, row):
        reference_id = row.get("invocation_reference_id")
        reference_hash = row.get("invocation_reference_integrity_hash")
        if not reference_id or not reference_hash or self._invocation_references is None:
            raise LegacyMissingPersistedLLMInvocationReference(
                "LEGACY_MISSING_PERSISTED_LLM_INVOCATION_REFERENCE"
            )
        with self._engine.connect() as connection:
            invocation_row = connection.execute(text(
                "SELECT * FROM llm_invocation_persisted_references WHERE reference_id=:id"
            ), {"id": reference_id}).mappings().first()
        if invocation_row is None:
            raise GovernedLLMDraftReferenceRejected("persisted invocation reference is unavailable")
        invocation_reference = self._invocation_references._decode_reference(invocation_row)
        if invocation_reference.integrity_hash != reference_hash:
            raise GovernedLLMDraftReferenceRejected("persisted invocation reference hash mismatch")
        return invocation_reference

    def _validate_exact(self, draft_id):
        tenant = current_tenant_context()
        with self._engine.connect() as connection:
            row = connection.execute(text(
                "SELECT * FROM governed_llm_drafts WHERE draft_id=:id"
            ), {"id": draft_id}).mappings().first()
            if row is None:
                raise LegacyMissingPersistedGovernedLLMDraftReference(
                    "LEGACY_MISSING_PERSISTED_GOVERNED_LLM_DRAFT_REFERENCE"
                )
            stream_rows = connection.execute(text("""SELECT * FROM governed_llm_drafts
              WHERE draft_stream_id=:stream AND version<=:version ORDER BY version,sequence_id"""),
              {"stream": row["draft_stream_id"], "version": row["version"]}).mappings().all()
            lifecycle_rows = connection.execute(text("""SELECT payload FROM governed_llm_draft_lifecycle_events
              WHERE draft_id=:id ORDER BY stream_position,sequence_id"""), {"id": draft_id}).scalars().all()
            invocation = connection.execute(text(
                "SELECT * FROM llm_invocations WHERE invocation_id=:id"
            ), {"id": row["invocation_id"]}).mappings().first()
            gateway_row = connection.execute(text(
                "SELECT * FROM persisted_gateway_inputs WHERE persisted_gateway_input_id=:id"
            ), {"id": invocation["persisted_gateway_input_id"] if invocation else None}).mappings().first()
        draft = self._decode_draft(row)
        if draft.tenant_id != tenant.tenant_id or draft.policy_version != tenant.policy_version:
            raise GovernedLLMDraftReferenceRejected("governed draft tenant or policy mismatch")
        decoded_chain = tuple(self._decode_draft(value) for value in stream_rows)
        if len(decoded_chain) != draft.version:
            raise GovernedLLMDraftReferenceRejected("governed draft version chain is incomplete")
        for position, value in enumerate(decoded_chain, 1):
            expected_predecessor = decoded_chain[position - 2].draft_id if position > 1 else None
            if value.version != position or value.predecessor != expected_predecessor:
                raise GovernedLLMDraftReferenceRejected("governed draft predecessor chain is invalid")
        lifecycle = tuple(self._codec.decode(value) for value in lifecycle_rows)
        if not lifecycle or not validate_lifecycle_chain(lifecycle):
            raise GovernedLLMDraftReferenceRejected("governed draft lifecycle chain is invalid")
        current = lifecycle[-1]
        if current.resulting_status is not GovernedLLMDraftLifecycleStatus.ACTIVE:
            raise GovernedLLMDraftReferenceRejected("governed draft lifecycle is not ACTIVE")
        gateway = self._validate_links(draft, invocation, gateway_row)
        return draft, invocation, gateway, current

    def _decode_draft(self, row):
        draft = self._codec.decode(row["payload"])
        if not validate_draft_integrity(draft, self._draft_attestor):
            raise GovernedLLMDraftReferenceRejected("persisted governed draft integrity is invalid")
        expected = (
            draft.draft_id, draft.draft_stream_id, draft.version, draft.predecessor,
            draft.invocation_id, draft.request_id, draft.correlation_id, draft.tenant_id,
            draft.output_classification, draft.review_status.value,
            draft.reviewable_content_hash, draft.integrity_hash, draft.issued_at,
            draft.policy_version,
        )
        actual = tuple(row[name] for name in (
            "draft_id", "draft_stream_id", "version", "predecessor", "invocation_id",
            "request_id", "correlation_id", "tenant_id", "output_classification",
            "review_status", "reviewable_content_hash", "integrity_hash", "issued_at",
            "policy_version",
        ))
        if actual != expected:
            raise GovernedLLMDraftReferenceRejected("governed draft relational/payload mismatch")
        return draft

    @staticmethod
    def _validate_links(draft, invocation, gateway_row):
        if invocation is None or gateway_row is None:
            raise GovernedLLMDraftReferenceRejected("invocation or persisted Gateway input is unavailable")
        upstream = draft.upstream_artifact_reference
        invocation_values = (
            invocation["invocation_id"], invocation["request_id"], invocation["correlation_id"],
            invocation["prompt_version_id"], invocation["provider"], invocation["model_id"],
            invocation["output_classification"], invocation["policy_version"],
            invocation["reviewable_content_hash"], invocation["upstream_artifact_type"],
            invocation["upstream_artifact_id"], invocation["upstream_artifact_version"],
        )
        draft_values = (
            draft.invocation_id, draft.request_id, draft.correlation_id,
            draft.prompt_version, draft.provider, draft.model, draft.output_classification,
            draft.policy_version, draft.reviewable_content_hash, upstream.artifact_type,
            upstream.artifact_id, upstream.artifact_version,
        )
        if invocation_values != draft_values or not invocation["persisted_gateway_input_id"]:
            raise GovernedLLMDraftReferenceRejected("canonical invocation linkage mismatch")
        from jmoraIs.infrastructure.persisted_gateway_input import _decode
        gateway = _decode(gateway_row["payload"])
        reference = gateway.upstream_artifact_reference
        relational = (
            gateway_row["persisted_gateway_input_id"], gateway_row["tenant_id"],
            gateway_row["artifact_type"], gateway_row["artifact_id"],
            gateway_row["artifact_version"], gateway_row["source_context"],
            gateway_row["integrity_reference"], gateway_row["policy_version"],
            gateway_row["dto_hash"], gateway_row["attestation"],
            gateway_row["record_integrity_hash"],
        )
        canonical = (
            gateway.persisted_gateway_input_id, reference.tenant_id,
            reference.artifact_type, reference.artifact_id, reference.artifact_version,
            reference.source_context, reference.integrity_reference,
            reference.policy_version, gateway.dto_hash, gateway.attestation,
            gateway.integrity_hash,
        )
        if (
            relational != canonical
            or gateway.integrity_hash != persisted_gateway_input_integrity_hash(gateway)
            or gateway.persisted_gateway_input_id != invocation["persisted_gateway_input_id"]
            or reference != upstream
        ):
            raise GovernedLLMDraftReferenceRejected("persisted Gateway input linkage is invalid")
        return gateway

    @staticmethod
    def _decode_reference(row, invocation_reference=None):
        from jmoraIs.gateway_input import UpstreamArtifactReference
        upstream = UpstreamArtifactReference(
            row["upstream_artifact_type"], row["upstream_artifact_id"],
            row["upstream_artifact_version"], row["tenant_id"],
            row["upstream_integrity_reference"], row["upstream_policy_version"],
            row["upstream_source_context"],
        )
        return PersistedGovernedLLMDraftReference(
            row["reference_id"], row["draft_id"], row["draft_stream_id"],
            row["draft_version"], row["predecessor"], row["tenant_id"],
            row["invocation_id"], row["request_id"], row["correlation_id"],
            row["persisted_gateway_input_id"], upstream, row["policy_version"],
            row["lifecycle_event_id"], row["lifecycle_status"],
            row["lifecycle_integrity_hash"], row["reviewable_content_hash"],
            row["draft_integrity_hash"], row["provenance_reference"],
            row["integrity_hash"], row["issued_at"],
            invocation_reference,
        )
