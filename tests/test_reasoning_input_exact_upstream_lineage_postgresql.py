import os
from dataclasses import replace
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from jmoraIs.appraisal import PostgreSQLGovernedEvidenceExactReferenceRepository
from jmoraIs.clinical.governance_persistence import SQLAlchemyGovernedEvidenceLifecycleRepository
from jmoraIs.clinical_state import PostgreSQLClinicalStateExactReferenceRepository
from jmoraIs.infrastructure.appraisal_persistence import PostgreSQLClinicalAppraisalRepository
from jmoraIs.infrastructure.postgresql_package_catalog import PostgreSQLPackageCatalogRepository
from jmoraIs.infrastructure.tenant_database import create_tenant_runtime_engine
from jmoraIs.application import ScientificEvidencePackagePort
from jmoraIs.reasoning_input import (
    ClinicalReasoningInputService, EvidenceDirection, EvidencePackageReference,
    EvidenceReferenceSummary, GovernedEvidenceReference,
    PatientClinicalStateReference, PostgreSQLClinicalReasoningInputRepository,
    PostgreSQLReasoningInputAuditAdapter, ReasoningUpstreamLineageStatus,
    PostgreSQLClinicalReasoningInputExactReferenceRepository,
)
from jmoraIs.infrastructure.cryptographic_replay import PostgreSQLCryptographicReplayEngine,ReplayIntegrityStatus
from jmoraIs.tenancy.context import TenantContextBinder
from jmoraIs.tenancy.domain import TenantContext
from jmoraIs.terminology import (
    CodeSystem, MappingConfidence, MappingOutcome, MappingReviewStatus,
    MappingType, MappedClinicalConcept,
    PostgreSQLTerminologyMappingGovernanceRepository,
    TerminologyMappingGovernanceService,
)
from tests.test_clinical_state_exact_reference_postgresql import persisted_states
from tests.test_governed_evidence_exact_reference_postgresql import setup as governed_setup
from tests.test_reasoning_input import NOW, TRACE, draft
from tests.test_terminology import concept


pytestmark = pytest.mark.integration


def test_all_exact_upstream_references_survive_restart_and_rls():
    url=os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url: pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    config=Config("alembic.ini");config.set_main_option("sqlalchemy.url",url);command.upgrade(config,"head")
    suffix=uuid4().hex
    tenant=TenantContext("reasoning-exact-"+suffix,"reasoning-exact-org-"+suffix,
        "principal","CLINICIAN","CLINICAL_DOCUMENTATION","ST-02","corr-"+suffix)
    owner=create_engine(url,future=True)
    with owner.begin() as connection:
        connection.execute(text("""INSERT INTO tenants
          (tenant_id,organization_id,display_name,status,policy_version,created_at)
          VALUES(:tenant,:organization,'Reasoning exact','ACTIVE',:policy,:at)"""),
          {"tenant":tenant.tenant_id,"organization":tenant.organization_id,
           "policy":tenant.policy_version,"at":NOW})
    writer=create_tenant_runtime_engine(url,runtime_role="jmorais_application_writer")
    binder=TenantContextBinder()
    with binder.bind_tenant(tenant):
        first_state,state=persisted_states(writer,tenant,suffix)
        state_owner=PostgreSQLClinicalStateExactReferenceRepository(writer,clock=lambda:NOW)
        state_owner.reference_for(first_state)
        state_reference=state_owner.reference_for(state)

        packages,appraisals,lifecycle,governed=governed_setup(owner,writer,suffix,tenant)
        governed_owner=PostgreSQLGovernedEvidenceExactReferenceRepository(
            writer,packages,appraisals,lifecycle,clock=lambda:NOW)
        governed_reference=governed_owner.reference_for(governed)

        terminology_owner=PostgreSQLTerminologyMappingGovernanceRepository(writer)
        term=replace(concept("reasoning-concept-"+suffix),version="terms-2026.1")
        mapped=MappedClinicalConcept(term.preferred_term,CodeSystem.ORTHOPEDIC,
            term.version,MappingOutcome.MAPPED,(term,),term.canonical_id,
            MappingConfidence.HIGH,False,("prov:"+suffix,))
        record=TerminologyMappingGovernanceService(terminology_owner,clock=lambda:NOW).persist(
            mapped,source_reference="state:"+suffix,target_concept_id=term.canonical_id,
            mapping_type=MappingType.EXACT,review_status=MappingReviewStatus.AUTO_MAPPED,
            review_required=False,mapping_method="deterministic",policy_version="ST-02")
        terminology_reference=terminology_owner.reference_for(record)

        legacy_state=PatientClinicalStateReference(state.state_id,**TRACE,
            patient_context_version=state.patient_context_version,
            clinical_state_version=state.state_version)
        legacy_evidence=GovernedEvidenceReference(governed.governed_evidence_id,**TRACE,
            evidence_package_reference_id=governed.evidence_package_id,
            direction=EvidenceDirection.SUPPORTING)
        package_reference=EvidencePackageReference(governed.evidence_package_id,**TRACE)
        reasoning_repository=PostgreSQLClinicalReasoningInputRepository(writer)
        service=ClinicalReasoningInputService(reasoning_repository,
            PostgreSQLReasoningInputAuditAdapter(writer),clock=lambda:NOW,
            clinical_states=state_owner,governed_evidence=governed_owner,
            terminology_governance=terminology_owner)
        reasoning=service.build(replace(draft(),subject_reference=state.pseudonymous_patient_id,
            patient_clinical_state=legacy_state,terminology_version=term.version,
            evidence=EvidenceReferenceSummary(supporting=(legacy_evidence,)),
            evidence_packages=(package_reference,),clinical_state_reference=state_reference,
            governed_evidence_references=(governed_reference,),
            terminology_governance_references=(terminology_reference,)),
            actor_id="system",source_reference="exact-assembly")
        assert reasoning.exact_upstream_lineage_status is ReasoningUpstreamLineageStatus.EXACT
        exact_owner=PostgreSQLClinicalReasoningInputExactReferenceRepository(writer,state_owner,
            governed_owner,terminology_owner,clock=lambda:NOW)
        reasoning_reference=exact_owner.reference_for(reasoning)
        assert exact_owner.get_exact(reasoning_reference)==reasoning
        input_id=reasoning.input_id

    del reasoning,service,reasoning_repository,state,state_owner,governed,governed_owner
    del terminology_owner,record,mapped,term,packages,appraisals,lifecycle,first_state
    writer.dispose()

    reader=create_tenant_runtime_engine(url,runtime_role="jmorais_application_reader")
    packages=ScientificEvidencePackagePort(catalog=PostgreSQLPackageCatalogRepository(owner),clock=lambda:NOW)
    with binder.bind_tenant(tenant):
        reread=PostgreSQLClinicalReasoningInputRepository(reader).get(input_id)
        assert reread.clinical_state_reference==state_reference
        assert reread.governed_evidence_references==(governed_reference,)
        assert reread.terminology_governance_references==(terminology_reference,)
        assert PostgreSQLClinicalStateExactReferenceRepository(reader).get_exact(state_reference).state_id==state_reference.state_id
        exact_governed=PostgreSQLGovernedEvidenceExactReferenceRepository(reader,packages,
            PostgreSQLClinicalAppraisalRepository(owner),SQLAlchemyGovernedEvidenceLifecycleRepository(reader),clock=lambda:NOW)
        assert exact_governed.get_exact(governed_reference).governed_evidence_id==governed_reference.governed_evidence_id
        exact_term=PostgreSQLTerminologyMappingGovernanceRepository(reader).get_exact(terminology_reference)
        assert exact_term.governance_record_id==terminology_reference.governance_record_id
        assert exact_term.target_concept_id==terminology_reference.target_concept_id
        exact_reasoning=PostgreSQLClinicalReasoningInputExactReferenceRepository(reader,
            PostgreSQLClinicalStateExactReferenceRepository(reader),exact_governed,
            PostgreSQLTerminologyMappingGovernanceRepository(reader))
        assert exact_reasoning.get_exact(reasoning_reference)==reread
    other=TenantContext("reasoning-other-"+suffix,"reasoning-other-org-"+suffix,
        "principal","CLINICIAN","CLINICAL_DOCUMENTATION","ST-02","other-corr")
    with owner.begin() as connection:
        connection.execute(text("INSERT INTO tenants(tenant_id,organization_id,display_name,status,policy_version,created_at) VALUES(:t,:o,'Other','ACTIVE',:p,:at)"),
            {"t":other.tenant_id,"o":other.organization_id,"p":other.policy_version,"at":NOW})
    with binder.bind_tenant(other):
        assert PostgreSQLClinicalReasoningInputRepository(reader).get(input_id) is None
        with pytest.raises(Exception): PostgreSQLClinicalStateExactReferenceRepository(reader).get_exact(state_reference)
        with pytest.raises(Exception): exact_governed.get_exact(governed_reference)
        with pytest.raises(Exception): exact_reasoning.get_exact(reasoning_reference)
    assert PostgreSQLClinicalReasoningInputRepository(reader).get(input_id) is None
    with owner.connect() as connection:
        assert connection.execute(text("SELECT rolbypassrls FROM pg_roles WHERE rolname='jmorais_application_reader'")).scalar_one() is False
    assert PostgreSQLCryptographicReplayEngine(owner).replay_clinical_reasoning_input_reference(reasoning_reference.reference_id,tenant_id=tenant.tenant_id).integrity_status is ReplayIntegrityStatus.VALID
    for statement in ("UPDATE clinical_reasoning_input_persisted_references SET policy_version='tampered' WHERE reference_id=:id","DELETE FROM clinical_reasoning_input_persisted_references WHERE reference_id=:id"):
        with pytest.raises(DBAPIError),owner.begin() as connection:connection.execute(text(statement),{"id":reasoning_reference.reference_id})
    reader.dispose();owner.dispose()
