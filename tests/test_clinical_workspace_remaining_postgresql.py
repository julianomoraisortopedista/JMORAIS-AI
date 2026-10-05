"""Remaining viewers: persisted owners, fresh compositions and read-only RLS."""
from contextlib import nullcontext
from dataclasses import FrozenInstanceError, replace
import os
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, event, text

from jmoraIs.clinical_workspace import RemainingClinicalWorkspace, WorkspaceReadRejected
from jmoraIs.clinical_state.exact_reference import ClinicalStateExactReferenceError
from jmoraIs.medical_documents.exact_reference import MedicalDocumentExactReferenceError
from jmoraIs.llm_human_review.exact_reference import HumanReviewExactReferenceError
from jmoraIs.tenancy.domain import MissingTenantContext
from tests import test_clinical_state_exact_reference_postgresql as state_source
from tests import test_audit_defense_reference_states_postgresql as defense_source
from tests import test_human_review_exact_reference_postgresql as review_source
from tests import test_governed_llm_draft_exact_reference_postgresql as draft_source

pytestmark = pytest.mark.integration
ERRORS = (ClinicalStateExactReferenceError, MedicalDocumentExactReferenceError,
          HumanReviewExactReferenceError, defense_source.AuditDefenseBoundaryRejected)


def seed(owner, writer, tenant, suffix):
    first, second = state_source.persisted_states(writer, tenant, suffix)
    states = state_source.PostgreSQLClinicalStateExactReferenceRepository(writer)
    refs = (states.reference_for(first), states.reference_for(second))
    timeline = states.timeline_reference_for(refs)
    document = replace(defense_source.document_value(), version_id="doc_" + uuid4().hex * 2,
                       document_stream_id="doc_" + uuid4().hex * 2)
    defense_source.PostgreSQLMedicalDocumentRepository(writer).append(document)
    documents = defense_source.PostgreSQLMedicalDocumentExactReferenceRepository(writer)
    document_ref = documents.reference_for(document)
    service, _, _, inp = defense_source.defense_setup()
    package = replace(service.generate(inp), package_id="def_" + uuid4().hex * 2,
                      stream_id="def_" + uuid4().hex * 2)
    defenses = defense_source.PostgreSQLAuditDefenseRepository(writer)
    defenses.append(package)
    pre = defenses.reference_for_pre_link(package)
    linked = defense_source.AuditDefenseTraceabilityService(documents, defenses,
        defense_source.PostgreSQLAuditDefenseEventAdapter(writer), clock=lambda: defense_source.NOW).link_stage11_document(pre, document_ref)
    # Approved fixture uses a mock provider only; no live LLM/network calls.
    draft, attestor, _, invocation = review_source.persisted_draft(owner, writer, suffix, tenant)
    invocations = review_source.PostgreSQLLLMInvocationExactReferenceRepository(writer)
    invocation_ref = invocations.reference_for(invocation)
    drafts = review_source.PostgreSQLGovernedLLMDraftExactReferenceRepository(
        writer, attestor, invocation_references=invocations)
    draft_ref = drafts.reference_for(draft, invocation_ref)
    unsigned = review_source.LLMHumanReviewEvent("review-" + suffix, draft.draft_id, draft.version,
        draft.invocation_id, draft.request_id, draft.correlation_id, tenant.tenant_id,
        draft.upstream_artifact_reference, review_source.HumanReviewStatus.PENDING_REVIEW,
        review_source.HumanReviewStatus.APPROVED_BY_REVIEWER, review_source.LLMReviewDecision.APPROVE,
        "reviewer-" + suffix, review_source.ReviewerRole.REVIEWER, tenant.organization_id, "ST-15.1",
        "REVIEW:test", review_source.NOW, 1, None, None, "")
    reviewed = replace(unsigned, integrity_hash=review_source.review_event_hash(unsigned))
    review_source.PostgreSQLLLMHumanReviewRepository(writer).append(reviewed)
    review_ref = review_source.PostgreSQLHumanReviewExactReferenceRepository(writer, drafts).reference_for(reviewed, draft_ref)
    return timeline, document_ref, review_ref, pre, linked


def compose(reader):
    invocations = review_source.PostgreSQLLLMInvocationExactReferenceRepository(reader)
    drafts = review_source.PostgreSQLGovernedLLMDraftExactReferenceRepository(reader,
        draft_source.GovernedDraftAttestor(draft_source.DRAFT_KEY,
            key_reference=draft_source.DRAFT_KEY_REFERENCE), invocation_references=invocations)
    return RemainingClinicalWorkspace(state_source.PostgreSQLClinicalStateExactReferenceRepository(reader),
        defense_source.PostgreSQLMedicalDocumentExactReferenceRepository(reader),
        review_source.PostgreSQLHumanReviewExactReferenceRepository(reader, drafts),
        defense_source.PostgreSQLAuditDefenseRepository(reader))


@pytest.fixture(scope="module")
def persisted():
    url = os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    owner = create_engine(url, future=True)
    with owner.connect() as c:
        assert c.execute(text("SHOW server_version_num")).scalar_one().startswith("16")
        assert MigrationContext.configure(c).get_current_heads() == tuple(
            ScriptDirectory.from_config(Config("alembic.ini")).get_heads()) == ("068_offline_medical_dependencies",)
    suffix = uuid4().hex
    tenants = tuple(review_source.TenantContext(prefix + suffix, prefix + "org-" + suffix, "service",
        "INTERNAL_SERVICE", "CLINICAL_VALIDATION", "MIP-10.1", "corr-" + suffix) for prefix in ("remaining-", "other-remaining-"))
    for tenant in tenants:
        state_source.insert_tenant(owner, tenant)
    writer = state_source.create_tenant_runtime_engine(url, runtime_role="jmorais_application_writer")
    try:
        with state_source.TenantContextBinder().bind_tenant(tenants[0]):
            references = seed(owner, writer, tenants[0], suffix)
    finally:
        writer.dispose()
        owner.dispose()
    return url, tenants, references


METHODS = ("timeline", "medical_document", "human_review", "audit_defense", "audit_defense")


def read_all(workspace, references):
    return tuple(getattr(workspace, method)(ref) for method, ref in zip(METHODS, references, strict=True))


def test_remaining_viewers_restart_and_read_only(persisted):
    url, tenants, refs = persisted
    results = []
    for _ in range(2):
        reader = state_source.create_tenant_runtime_engine(url, runtime_role="jmorais_application_reader")
        reader = reader.execution_options(postgresql_readonly=True)
        statements = []
        event.listen(reader, "before_cursor_execute", lambda c, cur, sql, p, ctx, many: statements.append(sql))
        try:
            with state_source.TenantContextBinder().bind_tenant(tenants[0]):
                results.append(read_all(compose(reader), refs))
                with reader.connect() as c:
                    assert c.execute(text("SHOW transaction_read_only")).scalar_one() == "on"
                    assert tuple(c.execute(text("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user")).one()) == (False, False)
            assert statements and all(sql.lstrip().split()[0].upper() in {"SELECT", "SET", "SHOW"} for sql in statements)
        finally:
            reader.dispose()
    assert results[0] == results[1]  # CLINICAL_WORKSPACE_REMAINING_VIEWERS_EXACT_REREAD
    timeline, document, review, pre, linked = results[1]
    assert tuple(e.source_reference for e in timeline.entries) == refs[0].state_references
    assert tuple(e.state_version for e in timeline.entries) == (1, 2)
    assert document.source_reference == refs[1] and document.provenance_references
    assert document.source_reference.traceability_hash
    assert review.decision == "APPROVE" and review.resulting_state == "APPROVED_BY_REVIEWER"
    assert review.source_reference.draft_reference == refs[2].draft_reference
    assert pre.state is defense_source.DefenseReferenceState.PRE_LINK and pre.stage11_document is None
    assert linked.state is defense_source.DefenseReferenceState.STAGE11_LINKED
    assert linked.stage11_document == document and linked.previous_package_id == refs[3].package_id
    assert linked.replay_status == "NOT_EVALUATED" and linked.completeness_verified is None
    for view in results[1]:
        with pytest.raises(FrozenInstanceError): view.integrity_status = "forged"


@pytest.mark.parametrize("index", range(5), ids=("timeline", "document", "review", "pre_link", "linked"))
def test_remaining_exact_failures_and_rls(persisted, index):
    url, tenants, refs = persisted
    reader = state_source.create_tenant_runtime_engine(url, runtime_role="jmorais_application_reader")
    try:
        method = getattr(compose(reader), METHODS[index])
        ref = refs[index]
        binder = state_source.TenantContextBinder()
        with binder.bind_tenant(tenants[0]):
            for bad in (None, "scalar-id", 1):
                with pytest.raises(WorkspaceReadRejected): method(bad)
            with pytest.raises(ERRORS): method(replace(ref, integrity_hash="f" * 64))
            id_field = "timeline_reference_id" if index == 0 else "reference_id"
            with pytest.raises(ERRORS): method(replace(ref, **{id_field: "unavailable"}))
            if index == 0:
                with pytest.raises(ERRORS): method(replace(ref, state_references=tuple(reversed(ref.state_references))))
        with binder.bind_tenant(tenants[1]), pytest.raises(WorkspaceReadRejected): method(ref)
        with pytest.raises(MissingTenantContext): method(ref)
        tables = ("clinical_state_timeline_references", "medical_document_persisted_references",
                  "human_review_persisted_references", "audit_defense_persisted_references", "audit_defense_persisted_references")
        with binder.bind_tenant(tenants[1]), reader.connect() as c:
            assert c.execute(text(f"SELECT count(*) FROM {tables[index]} WHERE {id_field}=:id"),
                {"id": getattr(ref, id_field)}).scalar_one() == 0
    finally:
        reader.dispose()


@pytest.mark.parametrize("index", range(5), ids=("timeline", "document", "review", "pre_link", "linked"))
def test_missing_persistence_fails_closed(persisted, index):
    url, tenants, refs = persisted
    owner = create_engine(url, future=True)
    class TransactionEngine:
        dialect = owner.dialect
        def __init__(self, c): self.c = c
        def connect(self): return nullcontext(self.c)
    tables = ("clinical_state_timeline_references", "medical_document_persisted_references",
              "human_review_persisted_references", "audit_defense_persisted_references", "audit_defense_persisted_references")
    id_field = "timeline_reference_id" if index == 0 else "reference_id"
    try:
        with owner.connect() as c:
            tx = c.begin()
            try:
                c.execute(text("SET LOCAL session_replication_role='replica'"))
                c.execute(text(f"DELETE FROM {tables[index]} WHERE {id_field}=:id"), {"id": getattr(refs[index], id_field)})
                with state_source.TenantContextBinder().bind_tenant(tenants[0]), pytest.raises(ERRORS):
                    getattr(compose(TransactionEngine(c)), METHODS[index])(refs[index])
            finally:
                tx.rollback()
    finally:
        owner.dispose()


@pytest.mark.parametrize("dependency", ("timeline_member", "stage11_document", "review_draft"))
def test_missing_exact_dependency_fails_closed(persisted, dependency):
    url, tenants, refs = persisted
    table, identifier, method, reference = {
        "timeline_member": ("clinical_state_persisted_references", refs[0].state_references[0].reference_id, "timeline", refs[0]),
        "stage11_document": ("medical_document_persisted_references", refs[1].reference_id, "audit_defense", refs[4]),
        "review_draft": ("governed_llm_draft_persisted_references", refs[2].draft_reference.reference_id, "human_review", refs[2]),
    }[dependency]
    owner = create_engine(url, future=True)
    class TransactionEngine:
        dialect = owner.dialect
        def __init__(self, c): self.c = c
        def connect(self): return nullcontext(self.c)
    try:
        with owner.connect() as c:
            tx = c.begin()
            try:
                c.execute(text("SET LOCAL session_replication_role='replica'"))
                c.execute(text(f"DELETE FROM {table} WHERE reference_id=:id"), {"id": identifier})
                with state_source.TenantContextBinder().bind_tenant(tenants[0]), pytest.raises(ERRORS):
                    getattr(compose(TransactionEngine(c)), method)(reference)
            finally:
                tx.rollback()
    finally:
        owner.dispose()
