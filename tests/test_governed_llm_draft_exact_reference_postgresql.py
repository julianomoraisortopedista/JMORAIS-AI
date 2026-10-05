from dataclasses import replace
from datetime import datetime, timezone
import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from jmoraIs.gateway_input import HMACPersistedGatewayInputAttestor
from jmoraIs.governed_llm_draft import (
    GovernedDraftAttestor, GovernedLLMDraftIssuanceService,
    GovernedLLMDraftLifecycleService, GovernedLLMDraftLifecycleStatus,
    GovernedLLMDraftReferenceRejected,
    PostgreSQLGovernedLLMDraftExactReferenceRepository,
    PostgreSQLGovernedLLMDraftRepository,
)
from jmoraIs.governed_llm_draft.exact_reference import governed_draft_reference_integrity
from jmoraIs.infrastructure.cryptographic_replay import PostgreSQLCryptographicReplayEngine, ReplayIntegrityStatus
from jmoraIs.infrastructure.persisted_gateway_input import PostgreSQLPersistedGatewayInputRepository
from jmoraIs.infrastructure.tenant_database import create_tenant_runtime_engine
from jmoraIs.llm_gateway import (
    CanonicalLLMGateway, LLMModel, LLMProvider, LLMRequest, MockProviderAdapter,
    PostgreSQLInvocationRepository, PostgreSQLLLMInvocationContextRepository,
    PostgreSQLPromptAuditRepository, PostgreSQLPromptRepository,
    PromptGovernanceService, ReviewPolicy,
)
from jmoraIs.llm_gateway.exact_reference_persistence import PostgreSQLLLMInvocationExactReferenceRepository
from jmoraIs.llm_gateway.exact_reference import (
    LegacyMissingPersistedLLMInvocationReference,
    LLMInvocationReferenceRejected,
    llm_invocation_reference_integrity,
)
from jmoraIs.medical_documents.gateway_input import MedicalDocumentGatewayInputIssuer
from jmoraIs.secrets.domain import KeyReference, SecretPurpose
from jmoraIs.tenancy.context import TenantContextBinder
from jmoraIs.tenancy.domain import MissingTenantContext, TenantContext
from tests.test_governed_llm_draft import DRAFT_KEY, DRAFT_KEY_REFERENCE
from tests.test_llm_gateway import request, response, template
from tests.test_medical_document_engine import setup as document_setup


pytestmark = pytest.mark.integration
NOW = datetime(2026, 9, 2, tzinfo=timezone.utc)
INPUT_KEY = b"governed-draft-exact-input-key-material-32"
KEY_REFERENCE = KeyReference("memory", "draft-exact-input", "v1", SecretPurpose.SIGNING_KEY)


def database():
    url = os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    return url, create_engine(url, future=True)


def persisted_draft(owner, writer, suffix, tenant, *, draft_attestor=None, subject_reference=None):
    document_engine, documents, _, document_input = document_setup()
    if subject_reference is not None:
        # Distinct synthetic subjects get distinct document (and draft) streams.
        document_input = replace(document_input, subject_reference=subject_reference)
    version = document_engine.generate(document_input, __import__("jmoraIs.medical_documents", fromlist=["DocumentType"]).DocumentType.CLINICAL_REPORT)
    input_attestor = HMACPersistedGatewayInputAttestor(INPUT_KEY)
    bound = MedicalDocumentGatewayInputIssuer(
        documents, input_attestor, clock=lambda: NOW, key_reference=KEY_REFERENCE,
    ).issue(version.document_stream_id, version.version)
    prompts = PostgreSQLPromptRepository(owner)
    prompt_template = replace(template(("MedicalDocument",)), template_id="draft-exact-template-" + suffix)
    prompt = PromptGovernanceService(prompts, PostgreSQLPromptAuditRepository(owner), clock=lambda: NOW).register(
        prompt_template, created_by="owner",
    )
    contexts = PostgreSQLLLMInvocationContextRepository(writer)
    invocations = PostgreSQLInvocationRepository(writer)
    gateway_inputs = PostgreSQLPersistedGatewayInputRepository(writer, input_attestor)
    gateway = CanonicalLLMGateway(
        prompts, PostgreSQLPromptAuditRepository(writer), invocations, contexts,
        (MockProviderAdapter((response(provider_request_id="draft-exact-provider-" + suffix, output_text="Governed exact draft " + suffix),)),),
        clock=lambda: NOW, persisted_input_attestor=input_attestor, persisted_inputs=gateway_inputs,
    )
    policy = ReviewPolicy("human-review", "MIP-10.1", True, False)
    gateway_request = request(
        prompt, input_dto=bound, review_policy=policy,
        request_id="draft-exact-request-" + suffix,
    )
    gateway_request = replace(
        gateway_request,
        model=LLMModel(LLMProvider.MOCK, "draft-exact-model", "1", 1.0, 2.0, True, "MIP-10.1"),
        requested_at=NOW,
    )
    result = gateway.invoke_persisted(gateway_request)
    invocation = invocations.history(gateway_request.request_id)[0]
    draft_attestor = draft_attestor or GovernedDraftAttestor(DRAFT_KEY,key_reference=DRAFT_KEY_REFERENCE)
    drafts = PostgreSQLGovernedLLMDraftRepository(writer, draft_attestor)
    draft = GovernedLLMDraftIssuanceService(
        drafts, invocations, contexts, input_attestor, draft_attestor, clock=lambda: NOW,
    ).issue(bound, result, policy)
    return draft, draft_attestor, drafts, invocation


def test_owner_issuance_restart_exact_reread_rls_append_only_and_replay():
    url, owner = database()
    suffix = uuid4().hex
    tenant = TenantContext("draft-exact-" + suffix, "draft-exact-org-" + suffix, "service", "INTERNAL_SERVICE", "CLINICAL_VALIDATION", "MIP-10.1", "corr-" + suffix)
    with owner.begin() as connection:
        connection.execute(text("INSERT INTO tenants(tenant_id,organization_id,display_name,status,policy_version,created_at) VALUES(:t,:o,'Draft exact','ACTIVE',:p,:at)"), {"t": tenant.tenant_id, "o": tenant.organization_id, "p": tenant.policy_version, "at": NOW})
    writer = create_tenant_runtime_engine(url, runtime_role="jmorais_application_writer")
    binder = TenantContextBinder()
    with binder.bind_tenant(tenant):
        draft, attestor, drafts, invocation = persisted_draft(owner, writer, suffix, tenant)
        invocation_references = PostgreSQLLLMInvocationExactReferenceRepository(writer, clock=lambda: NOW)
        invocation_reference = invocation_references.reference_for(invocation)
        references = PostgreSQLGovernedLLMDraftExactReferenceRepository(writer, attestor, invocation_references=invocation_references, clock=lambda: NOW)
        reference = references.reference_for(draft, invocation_reference)
        assert invocation_references.get_exact(invocation_reference) == invocation
        assert references.get_exact(reference) == draft
    draft_id = draft.draft_id
    del draft, drafts, references
    writer.dispose()

    reader = create_tenant_runtime_engine(url, runtime_role="jmorais_application_reader")
    with binder.bind_tenant(tenant):
        restarted_invocations = PostgreSQLLLMInvocationExactReferenceRepository(reader, clock=lambda: NOW)
        restarted = PostgreSQLGovernedLLMDraftExactReferenceRepository(reader, attestor, invocation_references=restarted_invocations, clock=lambda: NOW)
        reread = restarted.get_exact(reference)
    assert reread.draft_id == draft_id
    assert reread.version == reference.draft_version
    assert reread.invocation_id == reference.invocation_id
    assert reread.upstream_artifact_reference == reference.upstream_artifact_reference
    assert reread.reviewable_content_hash == reference.reviewable_content_hash
    assert reread.provenance

    other = TenantContext("other-" + suffix, "other-org-" + suffix, "service", "INTERNAL_SERVICE", "CLINICAL_VALIDATION", "MIP-10.1", "other-corr")
    with owner.begin() as connection:
        connection.execute(text("INSERT INTO tenants(tenant_id,organization_id,display_name,status,policy_version,created_at) VALUES(:t,:o,'Other','ACTIVE',:p,:at)"), {"t": other.tenant_id, "o": other.organization_id, "p": other.policy_version, "at": NOW})
    with binder.bind_tenant(other), pytest.raises(GovernedLLMDraftReferenceRejected):
        restarted.get_exact(reference)
    with binder.bind_tenant(other), pytest.raises(LLMInvocationReferenceRejected):
        restarted_invocations.get_exact(invocation_reference)
    with pytest.raises(MissingTenantContext):
        restarted.get_exact(reference)
    with binder.bind_tenant(tenant), pytest.raises(GovernedLLMDraftReferenceRejected):
        restarted.get_exact(reference.draft_id)
    with pytest.raises(DBAPIError), owner.begin() as connection:
        connection.execute(text("UPDATE governed_llm_draft_persisted_references SET policy_version='tampered' WHERE reference_id=:id"), {"id": reference.reference_id})
    with pytest.raises(DBAPIError), owner.begin() as connection:
        connection.execute(text("DELETE FROM governed_llm_draft_persisted_references WHERE reference_id=:id"), {"id": reference.reference_id})
    with pytest.raises(DBAPIError), owner.begin() as connection:
        connection.execute(text("UPDATE llm_invocation_persisted_references SET policy_version='tampered' WHERE reference_id=:id"), {"id": invocation_reference.reference_id})
    with pytest.raises(DBAPIError), owner.begin() as connection:
        connection.execute(text("DELETE FROM llm_invocation_persisted_references WHERE reference_id=:id"), {"id": invocation_reference.reference_id})
    replay = PostgreSQLCryptographicReplayEngine(owner).replay_governed_llm_draft_reference(reference.reference_id, tenant_id=tenant.tenant_id)
    assert replay.integrity_status is ReplayIntegrityStatus.VALID
    invocation_replay = PostgreSQLCryptographicReplayEngine(owner).replay_llm_invocation_reference(invocation_reference.reference_id, tenant_id=tenant.tenant_id)
    assert invocation_replay.integrity_status is ReplayIntegrityStatus.VALID
    reader.dispose()
    owner.dispose()


def test_tampered_reference_and_lifecycle_invalidation_fail_closed():
    url, owner = database()
    suffix = uuid4().hex
    tenant = TenantContext("draft-neg-" + suffix, "draft-neg-org-" + suffix, "service", "INTERNAL_SERVICE", "CLINICAL_VALIDATION", "MIP-10.1", "corr-neg-" + suffix)
    with owner.begin() as connection:
        connection.execute(text("INSERT INTO tenants(tenant_id,organization_id,display_name,status,policy_version,created_at) VALUES(:t,:o,'Draft negative','ACTIVE',:p,:at)"), {"t": tenant.tenant_id, "o": tenant.organization_id, "p": tenant.policy_version, "at": NOW})
    writer = create_tenant_runtime_engine(url, runtime_role="jmorais_application_writer")
    with TenantContextBinder().bind_tenant(tenant):
        draft, attestor, drafts, invocation = persisted_draft(owner, writer, suffix, tenant)
        invocation_references = PostgreSQLLLMInvocationExactReferenceRepository(writer, clock=lambda: NOW)
        invocation_reference = invocation_references.reference_for(invocation)
        with pytest.raises(LegacyMissingPersistedLLMInvocationReference):
            PostgreSQLGovernedLLMDraftExactReferenceRepository(writer, attestor).reference_for(draft)
        with pytest.raises(LLMInvocationReferenceRejected):
            invocation_references.get_exact(invocation.invocation_id)
        repository = PostgreSQLGovernedLLMDraftExactReferenceRepository(writer, attestor, invocation_references=invocation_references, clock=lambda: NOW)
        reference = repository.reference_for(draft, invocation_reference)
        invocation_mutations = (
            {"reference_id": "lir_" + "f" * 32},
            {"invocation_id": "wrong"}, {"request_id": "wrong"},
            {"tenant_id": "wrong"}, {"prompt_version": 2},
            {"persisted_gateway_input_id": "pgi_" + "0" * 64},
            {"invocation_integrity_hash": "0" * 64}, {"policy_version": "wrong"},
        )
        for mutation in invocation_mutations:
            with pytest.raises(LLMInvocationReferenceRejected):
                changed = replace(invocation_reference, **mutation, integrity_hash="0" * 64)
                changed = replace(changed, integrity_hash=llm_invocation_reference_integrity(changed))
                invocation_references.get_exact(changed)
        with pytest.raises(GovernedLLMDraftReferenceRejected):
            repository.reference_for(replace(draft, reviewable_content="tampered content"), invocation_reference)
        with pytest.raises(GovernedLLMDraftReferenceRejected):
            repository.reference_for(replace(draft, predecessor="forged predecessor"), invocation_reference)
        changes = (
            {"reference_id": "gdr_" + "f" * 32}, {"draft_id": "wrong"},
            {"draft_version": 2}, {"tenant_id": "wrong"}, {"invocation_id": "wrong"},
            {"request_id": "wrong"}, {"correlation_id": "wrong"},
            {"persisted_gateway_input_id": "pgi_" + "0" * 64},
            {"upstream_artifact_reference": replace(reference.upstream_artifact_reference, artifact_id="wrong")},
            {"reviewable_content_hash": "0" * 64}, {"draft_integrity_hash": "0" * 64},
            {"policy_version": "wrong"}, {"provenance_reference": "wrong"},
        )
        for mutation in changes:
            with pytest.raises(GovernedLLMDraftReferenceRejected):
                changed = replace(reference, **mutation, integrity_hash="0" * 64)
                changed = replace(changed, integrity_hash=governed_draft_reference_integrity(changed))
                repository.get_exact(changed)
        lifecycle = GovernedLLMDraftLifecycleService(drafts, drafts, attestor, clock=lambda: NOW)
        lifecycle.transition(draft.draft_id, draft.version, GovernedLLMDraftLifecycleStatus.INVALIDATED, reason_reference="POLICY:test", actor_reference="policy-engine", policy_version="MIP-10.1")
        with pytest.raises(GovernedLLMDraftReferenceRejected, match="ACTIVE"):
            repository.get_exact(reference)
    writer.dispose()
    owner.dispose()


def test_superseded_draft_reference_fails_closed():
    url, owner = database()
    suffix = uuid4().hex
    tenant = TenantContext("draft-super-" + suffix, "draft-super-org-" + suffix, "service", "INTERNAL_SERVICE", "CLINICAL_VALIDATION", "MIP-10.1", "corr-super-" + suffix)
    with owner.begin() as connection:
        connection.execute(text("INSERT INTO tenants(tenant_id,organization_id,display_name,status,policy_version,created_at) VALUES(:t,:o,'Draft superseded','ACTIVE',:p,:at)"), {"t": tenant.tenant_id, "o": tenant.organization_id, "p": tenant.policy_version, "at": NOW})
    writer = create_tenant_runtime_engine(url, runtime_role="jmorais_application_writer")
    with TenantContextBinder().bind_tenant(tenant):
        draft, attestor, drafts, invocation = persisted_draft(owner, writer, suffix, tenant)
        invocation_references = PostgreSQLLLMInvocationExactReferenceRepository(writer, clock=lambda: NOW)
        invocation_reference = invocation_references.reference_for(invocation)
        repository = PostgreSQLGovernedLLMDraftExactReferenceRepository(writer, attestor, invocation_references=invocation_references, clock=lambda: NOW)
        reference = repository.reference_for(draft, invocation_reference)
        GovernedLLMDraftLifecycleService(drafts, drafts, attestor, clock=lambda: NOW).transition(
            draft.draft_id, draft.version, GovernedLLMDraftLifecycleStatus.SUPERSEDED,
            reason_reference="REPLACED", actor_reference="draft-owner", policy_version="MIP-10.1",
        )
        with pytest.raises(GovernedLLMDraftReferenceRejected, match="ACTIVE"):
            repository.get_exact(reference)
    writer.dispose()
    owner.dispose()
