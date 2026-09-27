"""S003 viewers use real persisted owners; no workspace-owned clinical storage."""
from dataclasses import FrozenInstanceError, replace
import os
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, event, text

from jmoraIs.clinical_workspace import ClinicalWorkspace, WorkspaceReadRejected
from jmoraIs.clinical_state.exact_reference import ClinicalStateExactReferenceError
from jmoraIs.appraisal.exact_reference import GovernedEvidenceExactReferenceError
from jmoraIs.reasoning_input.exact_reference import ClinicalReasoningInputExactReferenceError
from jmoraIs.tenancy.domain import MissingTenantContext
# Reuse only existing focused boundary fixtures and their approved source owners.
from tests import test_reasoning_input_exact_upstream_lineage_postgresql as source

pytestmark = pytest.mark.integration


def seed(owner, writer, tenant, suffix):
    first, state = source.persisted_states(writer, tenant, suffix)
    states = source.PostgreSQLClinicalStateExactReferenceRepository(writer, clock=lambda: source.NOW)
    states.reference_for(first)
    state_ref = states.reference_for(state)
    packages, appraisals, lifecycle, governed = source.governed_setup(owner, writer, suffix, tenant)
    evidence = source.PostgreSQLGovernedEvidenceExactReferenceRepository(
        writer, packages, appraisals, lifecycle, clock=lambda: source.NOW)
    evidence_ref = evidence.reference_for(governed)
    terms = source.PostgreSQLTerminologyMappingGovernanceRepository(writer)
    term = replace(source.concept("workspace-" + suffix), version="terms-2026.1")
    mapped = source.MappedClinicalConcept(term.preferred_term, source.CodeSystem.ORTHOPEDIC,
        term.version, source.MappingOutcome.MAPPED, (term,), term.canonical_id,
        source.MappingConfidence.HIGH, False, ("prov:" + suffix,))
    record = source.TerminologyMappingGovernanceService(terms, clock=lambda: source.NOW).persist(
        mapped, source_reference="state:" + suffix, target_concept_id=term.canonical_id,
        mapping_type=source.MappingType.EXACT, review_status=source.MappingReviewStatus.AUTO_MAPPED,
        review_required=False, mapping_method="deterministic", policy_version="ST-02")
    term_ref = terms.reference_for(record)
    legacy_state = source.PatientClinicalStateReference(state.state_id, **source.TRACE,
        patient_context_version=state.patient_context_version, clinical_state_version=state.state_version)
    legacy_evidence = source.GovernedEvidenceReference(governed.governed_evidence_id, **source.TRACE,
        evidence_package_reference_id=governed.evidence_package_id, direction=source.EvidenceDirection.SUPPORTING)
    service = source.ClinicalReasoningInputService(source.PostgreSQLClinicalReasoningInputRepository(writer),
        source.PostgreSQLReasoningInputAuditAdapter(writer), clock=lambda: source.NOW,
        clinical_states=states, governed_evidence=evidence, terminology_governance=terms)
    value = service.build(replace(source.draft(), subject_reference=state.pseudonymous_patient_id,
        patient_clinical_state=legacy_state, terminology_version=term.version,
        evidence=source.EvidenceReferenceSummary(supporting=(legacy_evidence,)),
        evidence_packages=(source.EvidencePackageReference(governed.evidence_package_id, **source.TRACE),),
        clinical_state_reference=state_ref, governed_evidence_references=(evidence_ref,),
        terminology_governance_references=(term_ref,)), actor_id="system", source_reference="workspace-fixture")
    reasoning = source.PostgreSQLClinicalReasoningInputExactReferenceRepository(
        writer, states, evidence, terms, clock=lambda: source.NOW)
    return reasoning.reference_for(value)


def compose(reader):
    states = source.PostgreSQLClinicalStateExactReferenceRepository(reader)
    packages = source.ScientificEvidencePackagePort(
        catalog=source.PostgreSQLPackageCatalogRepository(reader), clock=lambda: source.NOW)
    evidence = source.PostgreSQLGovernedEvidenceExactReferenceRepository(reader, packages,
        source.PostgreSQLClinicalAppraisalRepository(reader),
        source.SQLAlchemyGovernedEvidenceLifecycleRepository(reader), clock=lambda: source.NOW)
    reasoning = source.PostgreSQLClinicalReasoningInputExactReferenceRepository(reader, states, evidence,
        source.PostgreSQLTerminologyMappingGovernanceRepository(reader))
    return ClinicalWorkspace(states, evidence, reasoning)


@pytest.fixture(scope="module")
def persisted():
    url = os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    owner = create_engine(url, future=True)
    with owner.connect() as c:
        assert c.execute(text("SHOW server_version_num")).scalar_one().startswith("16")
        assert MigrationContext.configure(c).get_current_heads() == tuple(
            ScriptDirectory.from_config(Config("alembic.ini")).get_heads()) == ("066_workspace_launch",)
    suffix = uuid4().hex
    tenants = tuple(source.TenantContext(prefix + suffix, prefix + "org-" + suffix, "principal",
        "CLINICIAN", "CLINICAL_DOCUMENTATION", "ST-02", "corr-" + suffix) for prefix in ("ws-", "other-ws-"))
    with owner.begin() as c:
        for tenant in tenants:
            c.execute(text("INSERT INTO tenants(tenant_id,organization_id,display_name,status,policy_version,created_at) VALUES(:t,:o,'Workspace tests','ACTIVE',:p,:at)"),
                {"t": tenant.tenant_id, "o": tenant.organization_id, "p": tenant.policy_version, "at": source.NOW})
    writer = source.create_tenant_runtime_engine(url, runtime_role="jmorais_application_writer")
    with source.TenantContextBinder().bind_tenant(tenants[0]):
        reference = seed(owner, writer, tenants[0], suffix)
    writer.dispose()
    owner.dispose()
    # Only persisted references and configuration survive source composition.
    return url, tenants, reference


@pytest.fixture
def runtime(persisted):
    url, tenants, reference = persisted
    reader = source.create_tenant_runtime_engine(url, runtime_role="jmorais_application_reader")
    reader = reader.execution_options(postgresql_readonly=True)
    statements = []
    event.listen(reader, "before_cursor_execute", lambda c, cur, sql, p, ctx, many: statements.append(sql))
    yield reader, compose(reader), tenants, reference
    assert statements
    assert all(sql.lstrip().split()[0].upper() in {"SELECT", "SET", "SHOW"} for sql in statements)
    reader.dispose()


def test_three_viewers_exact_reread_and_immutable_metadata(runtime, persisted):
    reader, workspace, tenants, reference = runtime
    with source.TenantContextBinder().bind_tenant(tenants[0]):
        before = workspace.read(reference)
        assert before.clinical_summary == workspace.clinical_summary(reference.clinical_state_reference)
        assert before.evidence == tuple(workspace.evidence(r) for r in reference.governed_evidence_references)
        assert before.explainability == workspace.explainability(reference)
        assert before.tenant_id == tenants[0].tenant_id
        assert before.clinical_summary.pseudonymous_patient_id == reference.subject_reference
        assert before.clinical_summary.review_status == "REVIEW_REQUIRED"
        assert before.evidence[0].source_reference.lifecycle_status == "ACTIVE"
        assert before.evidence[0].provenance_references and before.evidence[0].ledger_references
        assert before.explainability.source_reference.terminology_governance_references == reference.terminology_governance_references
        assert before.explainability.integrity_status == "OWNER_EXACT_REREAD"
        with pytest.raises(FrozenInstanceError): before.tenant_id = "changed"
        with pytest.raises(FrozenInstanceError): before.clinical_summary.review_status = "APPROVED"
        with reader.connect() as c:
            assert c.execute(text("SHOW transaction_read_only")).scalar_one() == "on"
            assert tuple(c.execute(text("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user")).one()) == (False, False)
    reader.dispose()
    del workspace
    fresh = source.create_tenant_runtime_engine(persisted[0], runtime_role="jmorais_application_reader")
    fresh = fresh.execution_options(postgresql_readonly=True)
    try:
        with source.TenantContextBinder().bind_tenant(tenants[0]):
            assert compose(fresh).read(reference) == before  # CLINICAL_WORKSPACE_EXACT_REREAD
    finally:
        fresh.dispose()


def test_reference_failures_and_tenant_isolation(runtime):
    reader, workspace, tenants, reference = runtime
    methods = ((workspace.clinical_summary, reference.clinical_state_reference, ClinicalStateExactReferenceError),
               (workspace.evidence, reference.governed_evidence_references[0], GovernedEvidenceExactReferenceError),
               (workspace.explainability, reference, ClinicalReasoningInputExactReferenceError),
               (workspace.read, reference, ClinicalReasoningInputExactReferenceError))
    binder = source.TenantContextBinder()
    for method, ref, error in methods:
        with binder.bind_tenant(tenants[0]):
            for bad in (None, ref.reference_id, 1):
                with pytest.raises(WorkspaceReadRejected): method(bad)
            for bad in (replace(ref, reference_id="unavailable"), replace(ref, integrity_hash="f" * 64)):
                with pytest.raises(error): method(bad)
        with binder.bind_tenant(tenants[1]), pytest.raises(WorkspaceReadRejected): method(ref)
        with pytest.raises(MissingTenantContext): method(ref)
    with binder.bind_tenant(tenants[1]), reader.connect() as c:
        for table, ref in (("clinical_state_persisted_references", reference.clinical_state_reference),
                           ("governed_evidence_persisted_references", reference.governed_evidence_references[0]),
                           ("clinical_reasoning_input_persisted_references", reference)):
            assert c.execute(text(f"SELECT count(*) FROM {table} WHERE reference_id=:r"), {"r": ref.reference_id}).scalar_one() == 0


def test_missing_persisted_source_fails_closed(persisted):
    _, tenants, reference = persisted
    owner = create_engine(persisted[0], future=True)
    # Privileged fault injection is rolled back; owners must not return cached data.
    from contextlib import nullcontext
    class TransactionEngine:
        dialect = owner.dialect
        def __init__(self, connection): self.connection = connection
        def connect(self): return nullcontext(self.connection)
    try:
        for table, ref in (("clinical_state_persisted_references", reference.clinical_state_reference),
                           ("governed_evidence_persisted_references", reference.governed_evidence_references[0]),
                           ("clinical_reasoning_input_persisted_references", reference)):
            with owner.connect() as c:
                tx = c.begin()
                try:
                    c.execute(text("SET LOCAL session_replication_role='replica'"))
                    c.execute(text(f"DELETE FROM {table} WHERE reference_id=:r"), {"r": ref.reference_id})
                    with source.TenantContextBinder().bind_tenant(tenants[0]), pytest.raises(
                        (ClinicalStateExactReferenceError, GovernedEvidenceExactReferenceError, ClinicalReasoningInputExactReferenceError)):
                        compose(TransactionEngine(c)).read(reference)
                finally:
                    tx.rollback()
    finally:
        owner.dispose()
