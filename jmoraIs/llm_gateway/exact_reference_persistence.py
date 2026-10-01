from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import text

from jmoraIs.gateway_input import persisted_gateway_input_integrity_hash
from jmoraIs.tenancy.context import current_tenant_context

from .domain import InvocationStatus, LLMInvocation, LLMOutputClassification
from .application import CanonicalLLMGateway, PromptGovernanceService
from .exact_reference import (
    LegacyMissingPersistedLLMInvocationReference,
    LLMInvocationReferenceRejected,
    PersistedLLMInvocationReference,
    llm_invocation_integrity_hash,
    llm_invocation_reference_integrity,
    validate_llm_invocation_reference,
)
from .persistence import LLMGatewayJsonCodec, PostgreSQLLLMInvocationContextRepository


class PostgreSQLLLMInvocationExactReferenceRepository:
    """Gateway-owned exact reference boundary for immutable persisted invocations."""

    def __init__(self, engine, *, clock=None, codec=None):
        if engine.dialect.name != "postgresql":
            raise ValueError("LLM invocation exact references require PostgreSQL")
        self._engine = engine
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._codec = codec or LLMGatewayJsonCodec()

    def reference_for(self, invocation: LLMInvocation) -> PersistedLLMInvocationReference:
        if not isinstance(invocation, LLMInvocation):
            raise LLMInvocationReferenceRejected("typed LLMInvocation is required")
        canonical, context, prompt, gateway = self._validate_exact(invocation.invocation_id)
        if canonical != invocation:
            raise LLMInvocationReferenceRejected("invocation does not match canonical persistence")
        issued_at = self._clock()
        unsigned = PersistedLLMInvocationReference(
            "lir_" + uuid4().hex, invocation.invocation_id, invocation.request_id,
            invocation.correlation_id, context["tenant_id"], context["principal_id"],
            context["purpose"], invocation.prompt_version_id, prompt["template_id"],
            prompt["version"], prompt["prompt_hash"], invocation.persisted_gateway_input_id,
            invocation.upstream_reference, invocation.provider.value, invocation.model_id,
            invocation.policy_version, invocation.output_classification.value,
            invocation.status.value, invocation.temperature, invocation.seed,
            llm_invocation_integrity_hash(invocation), "0" * 64, issued_at,
        )
        reference = replace(unsigned, integrity_hash=llm_invocation_reference_integrity(unsigned))
        upstream = reference.upstream_artifact_reference
        with self._engine.begin() as connection:
            connection.execute(text("""INSERT INTO llm_invocation_persisted_references
              (reference_id,invocation_id,request_id,correlation_id,tenant_id,principal_id,purpose,
               prompt_version_id,prompt_template_id,prompt_version,prompt_hash,persisted_gateway_input_id,
               upstream_artifact_type,upstream_artifact_id,upstream_artifact_version,
               upstream_integrity_reference,upstream_policy_version,upstream_source_context,
               provider,model_id,policy_version,output_classification,invocation_status,
               temperature,seed,invocation_integrity_hash,integrity_hash,issued_at)
              VALUES(:reference,:invocation,:request,:correlation,:tenant,:principal,:purpose,
               :prompt_id,:template,:prompt_version,:prompt_hash,:gateway,:upstream_type,
               :upstream_id,:upstream_version,:upstream_integrity,:upstream_policy,:upstream_source,
               :provider,:model,:policy,:classification,:status,:temperature,:seed,
               :invocation_hash,:integrity,:issued)"""), {
                "reference": reference.reference_id, "invocation": reference.invocation_id,
                "request": reference.request_id, "correlation": reference.correlation_id,
                "tenant": reference.tenant_id, "principal": reference.principal_id,
                "purpose": reference.purpose, "prompt_id": reference.prompt_version_id,
                "template": reference.prompt_template_id, "prompt_version": reference.prompt_version,
                "prompt_hash": reference.prompt_hash,
                "gateway": reference.persisted_gateway_input_id,
                "upstream_type": upstream.artifact_type, "upstream_id": upstream.artifact_id,
                "upstream_version": upstream.artifact_version,
                "upstream_integrity": upstream.integrity_reference,
                "upstream_policy": upstream.policy_version,
                "upstream_source": upstream.source_context,
                "provider": reference.provider, "model": reference.model_id,
                "policy": reference.policy_version,
                "classification": reference.output_classification,
                "status": reference.invocation_status, "temperature": reference.temperature,
                "seed": reference.seed, "invocation_hash": reference.invocation_integrity_hash,
                "integrity": reference.integrity_hash, "issued": reference.issued_at,
            })
        return reference

    def get_exact(self, reference: PersistedLLMInvocationReference) -> LLMInvocation:
        if not validate_llm_invocation_reference(reference):
            raise LLMInvocationReferenceRejected("authentic owner-issued invocation reference is required")
        tenant = current_tenant_context()
        if reference.tenant_id != tenant.tenant_id or reference.policy_version != CanonicalLLMGateway.POLICY:
            raise LLMInvocationReferenceRejected("invocation tenant or policy mismatch")
        with self._engine.connect() as connection:
            row = connection.execute(text(
                "SELECT * FROM llm_invocation_persisted_references WHERE reference_id=:id"
            ), {"id": reference.reference_id}).mappings().first()
        if row is None:
            raise LegacyMissingPersistedLLMInvocationReference(
                "LEGACY_MISSING_PERSISTED_LLM_INVOCATION_REFERENCE"
            )
        persisted = self._decode_reference(row)
        if persisted != reference:
            raise LLMInvocationReferenceRejected("persisted invocation reference is inconsistent")
        invocation, context, prompt, gateway = self._validate_exact(reference.invocation_id)
        actual = self._linkage(invocation, context, prompt)
        expected = self._reference_linkage(reference)
        if actual != expected or gateway.persisted_gateway_input_id != reference.persisted_gateway_input_id:
            raise LLMInvocationReferenceRejected("invocation reference linkage mismatch")
        return invocation

    def _validate_exact(self, invocation_id):
        tenant = current_tenant_context()
        with self._engine.connect() as connection:
            rows = connection.execute(text(
                "SELECT * FROM llm_invocations WHERE invocation_id=:id"
            ), {"id": invocation_id}).mappings().all()
            if len(rows) != 1:
                raise LegacyMissingPersistedLLMInvocationReference(
                    "LEGACY_MISSING_PERSISTED_LLM_INVOCATION_REFERENCE"
                )
            row = rows[0]
            context = connection.execute(text(
                "SELECT * FROM llm_invocation_contexts WHERE request_id=:id"
            ), {"id": row["request_id"]}).mappings().first()
            prompt = connection.execute(text(
                "SELECT * FROM llm_prompt_versions WHERE prompt_version_id=:id"
            ), {"id": row["prompt_version_id"]}).mappings().first()
            gateway_row = connection.execute(text(
                "SELECT * FROM persisted_gateway_inputs WHERE persisted_gateway_input_id=:id"
            ), {"id": row["persisted_gateway_input_id"]}).mappings().first()
        invocation = self._codec.decode(row["payload"])
        if not isinstance(invocation, LLMInvocation):
            raise LLMInvocationReferenceRejected("persisted invocation payload is invalid")
        self._validate_invocation_row(invocation, row)
        if context is None or context["tenant_id"] != tenant.tenant_id:
            raise LLMInvocationReferenceRejected("invocation context tenant mismatch")
        if (
            context["policy_version"] != invocation.policy_version
            or invocation.policy_version != CanonicalLLMGateway.POLICY
            or context["correlation_id"] != invocation.correlation_id
        ):
            raise LLMInvocationReferenceRejected("invocation context linkage mismatch")
        context_value = __import__("jmoraIs.llm_gateway.domain", fromlist=["LLMInvocationContext"]).LLMInvocationContext(
            context["correlation_id"], context["tenant_id"], context["principal_id"],
            context["purpose"], context["policy_version"], context["request_id"], context["issued_at"],
        )
        if context["integrity_hash"] != PostgreSQLLLMInvocationContextRepository._hash(context_value):
            raise LLMInvocationReferenceRejected("invocation context integrity mismatch")
        if prompt is None:
            raise LLMInvocationReferenceRejected("exact PromptVersion linkage is unavailable")
        prompt_value = self._codec.decode(prompt["payload"])
        prompt_expected = (
            prompt_value.prompt_version_id, prompt_value.template_id, prompt_value.version,
            prompt_value.prompt_hash, prompt_value.template.policy_version,
        )
        prompt_actual = tuple(prompt[name] for name in (
            "prompt_version_id", "template_id", "version", "prompt_hash", "policy_version",
        ))
        if (
            prompt_actual != prompt_expected
            or prompt_value.prompt_version_id != invocation.prompt_version_id
            or PromptGovernanceService._hash(prompt_value.template) != prompt_value.prompt_hash
        ):
            raise LLMInvocationReferenceRejected("PromptVersion relational/payload linkage mismatch")
        gateway = self._validate_gateway(invocation, gateway_row, context["tenant_id"])
        return invocation, context, prompt, gateway

    @staticmethod
    def _validate_invocation_row(invocation, row):
        expected = (
            invocation.invocation_id, invocation.request_id, invocation.prompt_version_id,
            invocation.provider.value, invocation.model_id, invocation.status.value,
            invocation.correlation_id,
            invocation.output_classification.value if invocation.output_classification else None,
            invocation.temperature, invocation.seed,
            invocation.upstream_reference.artifact_type if invocation.upstream_reference else None,
            invocation.upstream_reference.artifact_id if invocation.upstream_reference else None,
            invocation.upstream_reference.artifact_version if invocation.upstream_reference else None,
            invocation.persisted_gateway_input_id, invocation.reviewable_content_hash,
            invocation.occurred_at, invocation.policy_version,
        )
        actual = tuple(row[name] for name in (
            "invocation_id", "request_id", "prompt_version_id", "provider", "model_id",
            "status", "correlation_id", "output_classification", "temperature", "seed",
            "upstream_artifact_type", "upstream_artifact_id", "upstream_artifact_version",
            "persisted_gateway_input_id", "reviewable_content_hash", "occurred_at", "policy_version",
        ))
        if actual != expected:
            raise LLMInvocationReferenceRejected("invocation relational/payload mismatch")
        if invocation.status not in {InvocationStatus.SUCCEEDED, InvocationStatus.BLOCKED}:
            raise LLMInvocationReferenceRejected("invocation is not complete")
        if invocation.output_classification is None:
            raise LLMInvocationReferenceRejected("invocation classification is missing")
        if invocation.output_classification is LLMOutputClassification.BLOCKED and invocation.status is not InvocationStatus.BLOCKED:
            raise LLMInvocationReferenceRejected("invocation status/classification mismatch")
        if invocation.output_classification is not LLMOutputClassification.BLOCKED and invocation.status is not InvocationStatus.SUCCEEDED:
            raise LLMInvocationReferenceRejected("invocation status/classification mismatch")
        if invocation.temperature is None or not 0 <= invocation.temperature <= 2:
            raise LLMInvocationReferenceRejected("invocation generation configuration is invalid")
        if invocation.upstream_reference is None or not invocation.persisted_gateway_input_id:
            raise LLMInvocationReferenceRejected("invocation persisted Gateway input linkage is missing")

    @staticmethod
    def _validate_gateway(invocation, row, tenant_id):
        if row is None:
            raise LLMInvocationReferenceRejected("PersistedGatewayInputRecord is unavailable")
        from jmoraIs.infrastructure.persisted_gateway_input import _decode
        gateway = _decode(row["payload"])
        reference = gateway.upstream_artifact_reference
        expected = (
            gateway.persisted_gateway_input_id, reference.tenant_id, reference.artifact_type,
            reference.artifact_id, reference.artifact_version, reference.source_context,
            reference.integrity_reference, reference.policy_version, gateway.dto_hash,
            gateway.attestation, gateway.integrity_hash,
        )
        actual = tuple(row[name] for name in (
            "persisted_gateway_input_id", "tenant_id", "artifact_type", "artifact_id",
            "artifact_version", "source_context", "integrity_reference", "policy_version",
            "dto_hash", "attestation", "record_integrity_hash",
        ))
        if (
            actual != expected
            or gateway.integrity_hash != persisted_gateway_input_integrity_hash(gateway)
            or gateway.persisted_gateway_input_id != invocation.persisted_gateway_input_id
            or reference != invocation.upstream_reference
            or reference.tenant_id != tenant_id
        ):
            raise LLMInvocationReferenceRejected("PersistedGatewayInput linkage is invalid")
        return gateway

    @staticmethod
    def _linkage(invocation, context, prompt):
        return (
            invocation.invocation_id, invocation.request_id, invocation.correlation_id,
            context["tenant_id"], context["principal_id"], context["purpose"],
            invocation.prompt_version_id, prompt["template_id"], prompt["version"],
            prompt["prompt_hash"], invocation.persisted_gateway_input_id,
            invocation.upstream_reference, invocation.provider.value, invocation.model_id,
            invocation.policy_version, invocation.output_classification.value,
            invocation.status.value, invocation.temperature, invocation.seed,
            llm_invocation_integrity_hash(invocation),
        )

    @staticmethod
    def _reference_linkage(reference):
        return (
            reference.invocation_id, reference.request_id, reference.correlation_id,
            reference.tenant_id, reference.principal_id, reference.purpose,
            reference.prompt_version_id, reference.prompt_template_id,
            reference.prompt_version, reference.prompt_hash,
            reference.persisted_gateway_input_id, reference.upstream_artifact_reference,
            reference.provider, reference.model_id, reference.policy_version,
            reference.output_classification, reference.invocation_status,
            reference.temperature, reference.seed, reference.invocation_integrity_hash,
        )

    @staticmethod
    def _decode_reference(row):
        from jmoraIs.gateway_input import UpstreamArtifactReference
        upstream = UpstreamArtifactReference(
            row["upstream_artifact_type"], row["upstream_artifact_id"],
            row["upstream_artifact_version"], row["tenant_id"],
            row["upstream_integrity_reference"], row["upstream_policy_version"],
            row["upstream_source_context"],
        )
        return PersistedLLMInvocationReference(
            row["reference_id"], row["invocation_id"], row["request_id"],
            row["correlation_id"], row["tenant_id"], row["principal_id"],
            row["purpose"], row["prompt_version_id"], row["prompt_template_id"],
            row["prompt_version"], row["prompt_hash"], row["persisted_gateway_input_id"],
            upstream, row["provider"], row["model_id"], row["policy_version"],
            row["output_classification"], row["invocation_status"], row["temperature"],
            row["seed"], row["invocation_integrity_hash"], row["integrity_hash"],
            row["issued_at"],
        )
