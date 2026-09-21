import os
from dataclasses import replace
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from jmoraIs.appraisal.persistence import SQLAlchemyGovernedEvidenceRepository
from jmoraIs.application.evidence_packages import ScientificEvidencePackagePort
from jmoraIs.application.scientific_citations import ScientificCitationService
from jmoraIs.clinical import (AuthorizedRecommendationReviewService,
    GovernedEvidenceReevaluationService, InMemoryGovernedDecisionAuditRepository,
    InMemoryReviewerAuthorizationAdapter, ReviewAuthorizationPolicy,
    ReviewerIdentity, ReviewerRole)
from jmoraIs.clinical.governance_persistence import SQLAlchemyGovernedEvidenceLifecycleRepository
from jmoraIs.clinical_state.persistence import PostgreSQLClinicalStateRepository
from jmoraIs.evidence_ledger import hash_payload
from jmoraIs.guideline_engine import PostgreSQLRecommendationRepository
from jmoraIs.infrastructure.postgresql_package_catalog import PostgreSQLCanonicalLedger, PostgreSQLPackageCatalogRepository
from jmoraIs.infrastructure.scientific_citation_persistence import PostgreSQLScientificCitationRepository
from jmoraIs.infrastructure.tenant_database import create_tenant_runtime_engine
from jmoraIs.medical_documents import (CanonicalDocumentCitationAdapter, DocumentStatus, DocumentType,
    InMemoryDocumentTemplateRepository, MedicalDocumentEngine, PostgreSQLDocumentAuditAdapter,
    PostgreSQLGovernedDocumentClinicalStateAdapter, PostgreSQLGovernedDocumentTerminologyAdapter,
    PostgreSQLMedicalDocumentRepository, canonical_templates)
from jmoraIs.orthopedic_intelligence import PostgreSQLOrthopedicAssessmentRepository
from jmoraIs.reasoning_input import (ClinicalReasoningInputService, EvidencePackageReference,
    GovernedEvidenceReference, PostgreSQLClinicalReasoningInputRepository,
    PostgreSQLReasoningInputAuditAdapter)
from jmoraIs.tenancy.context import TenantContextBinder
from jmoraIs.tenancy.domain import TenantContext
from jmoraIs.terminology import PostgreSQLTerminologyRepository
from jmoraIs.vancouver import StrictVancouverFormatter
from tests.test_evidence_package_boundary import NOW as SCI_NOW, verified_article
from tests.test_governed_document_clinical_state import rich_state
from tests.test_guideline_engine import setup as guideline_setup, evidence, guideline
from tests.test_orthopedic_intelligence import engine as orthopedic_setup, finding, view
from tests.test_reasoning_input import draft
from tests.test_terminology import concept

pytestmark = pytest.mark.integration


def _context(tenant, organization, correlation):
    return TenantContext(tenant, organization, "stage11-service", "INTERNAL_SERVICE",
                         "CLINICAL_VALIDATION", "iam-policy-v1", correlation)


def test_complete_stage11_real_services_restart_rls_and_append_only():
    url = os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url: pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    config = Config("alembic.ini"); config.set_main_option("sqlalchemy.url", url); command.upgrade(config, "head")
    owner = create_engine(url, future=True); suffix = uuid4().hex
    tenant, organization = f"stage11-{suffix}", f"org-stage11-{suffix}"
    other = _context(f"other-{suffix}", f"other-org-{suffix}", f"corr-other-{suffix}")
    current = _context(tenant, organization, f"corr-stage11-{suffix}")
    with owner.begin() as connection:
        connection.execute(text("INSERT INTO tenants(tenant_id,organization_id,display_name,status,policy_version,created_at) VALUES(:t,:o,'Stage 11','ACTIVE','iam-policy-v1',:at)"), {"t":tenant,"o":organization,"at":SCI_NOW})

    # Shared/global scientific truth: authoritative fixture -> package -> Vancouver -> citation record.
    article = verified_article(); article.article_id = f"article-{suffix}"; article.authors = ["Doe J"]
    article.journal = "Governed Orthopedic Journal"; article.publication_year = 2025
    ledger = PostgreSQLCanonicalLedger(owner); claim = ledger.create_claim("Synthetic governed outcome", claim_id=f"claim-{suffix}", created_at=SCI_NOW)
    _, support, _ = ledger.register_evidence(claim_id=claim.claim_id, source_name="NCBI PubMed", source_type="pubmed",
        passage="Synthetic deterministic result", pmid=article.pmid, payload_hash=hash_payload({"article":article.article_id}),
        retrieved_at=SCI_NOW, verification_version="ST-02", pipeline_version="ST-04", policy_version="ST-02",
        support_direction="supporting", occurred_at=SCI_NOW)
    packages = ScientificEvidencePackagePort(catalog=PostgreSQLPackageCatalogRepository(owner), clock=lambda:SCI_NOW)
    package = packages.issue(article=article, ledger=ledger, claim_id=claim.claim_id, support_ids=(support.support_id,), pipeline_version="ST-04")
    vancouver = StrictVancouverFormatter(packages, clock=lambda:SCI_NOW).render(package_id=package.package_id, article=article)
    citation = ScientificCitationService(PostgreSQLScientificCitationRepository(owner), packages, clock=lambda:SCI_NOW).issue(package_id=package.package_id, article=article, vancouver_reference=vancouver)

    binder = TenantContextBinder(); writer = create_tenant_runtime_engine(url, runtime_role="jmorais_application_writer")
    governed = replace(evidence(), governed_evidence_id=f"governed-{suffix}", evidence_package_id=package.package_id)
    state_reference = f"cs-{suffix}"; patient = "pt_" + suffix * 2
    state = replace(rich_state(), state_id=state_reference, pseudonymous_patient_id=patient,
                    patient_context_version=3, state_version=1, previous_state_id=None)
    with binder.bind_tenant(current):
        SQLAlchemyGovernedEvidenceRepository(writer).append(governed)
        PostgreSQLClinicalStateRepository(writer).append(state)
        reasoning_repository = PostgreSQLClinicalReasoningInputRepository(writer)
        reasoning_service = ClinicalReasoningInputService(reasoning_repository, PostgreSQLReasoningInputAuditAdapter(writer), clock=lambda:SCI_NOW)
        source = draft(subject_reference=patient, patient_clinical_state=replace(draft().patient_clinical_state, reference_id=state_reference, clinical_state_version=1),
            evidence_packages=(replace(draft().evidence_packages[0], reference_id=package.package_id),),
            evidence=replace(draft().evidence, supporting=(replace(draft().evidence.supporting[0], reference_id=governed.governed_evidence_id, evidence_package_reference_id=package.package_id),)))
        reasoning_service.build(source, actor_id="stage11-assembler", source_reference="persisted-inputs")
        reasoning = reasoning_service.mark_reviewed(patient, actor_id="clinical-reviewer", source_reference="review:stage11")
        rule=replace(guideline(),governed_evidence_ids=(governed.governed_evidence_id,))
        guideline_engine, _, _ = guideline_setup(guidelines=(rule,),evidences=(governed,)); guideline_set = guideline_engine.create_recommendation_set(reasoning)
        guideline_repository=PostgreSQLRecommendationRepository(writer);guideline_repository.append(guideline_set)
        guideline_reference=guideline_repository.reference_for(guideline_set)
        orthopedic_engine, _, _, _ = orthopedic_setup(replace(view(finding()), state_reference_id=state_reference, state_version=1), evidences=(governed,), guidelines=guideline_set)
        orthopedic_set = orthopedic_engine.generate(reasoning); orthopedic_repository=PostgreSQLOrthopedicAssessmentRepository(writer);orthopedic_repository.append(orthopedic_set);orthopedic_reference=orthopedic_repository.reference_for(orthopedic_set)
    for identifier in ("locking", "stiffness", "concept-1"):
        term = replace(concept(), canonical_id=identifier, preferred_term=identifier, display_name=identifier.title(),
                       synonyms=(), version=reasoning.terminology_version)
        PostgreSQLTerminologyRepository(owner).append(identifier, term)

    # Release and recompose every Stage-11 dependency from canonical persistence.
    del reasoning_service, reasoning_repository, guideline_engine, orthopedic_engine, ledger, packages
    reader = create_tenant_runtime_engine(url, runtime_role="jmorais_application_reader")
    writer2 = create_tenant_runtime_engine(url, runtime_role="jmorais_application_writer")
    package_query = ScientificEvidencePackagePort(catalog=PostgreSQLPackageCatalogRepository(owner), clock=lambda:SCI_NOW)
    scientific_query = ScientificCitationService(PostgreSQLScientificCitationRepository(owner), package_query, clock=lambda:SCI_NOW)
    evidence_query = SQLAlchemyGovernedEvidenceRepository(reader)
    lifecycle = GovernedEvidenceReevaluationService(package_query, SQLAlchemyGovernedEvidenceLifecycleRepository(writer2), clock=lambda:SCI_NOW)
    review = AuthorizedRecommendationReviewService(InMemoryReviewerAuthorizationAdapter((ReviewerIdentity("stage11-reviewer",ReviewerRole.SENIOR_REVIEWER),)), InMemoryGovernedDecisionAuditRepository(), ReviewAuthorizationPolicy(), clock=lambda:SCI_NOW)
    documents = PostgreSQLMedicalDocumentRepository(writer2)
    engine = MedicalDocumentEngine(PostgreSQLGovernedDocumentClinicalStateAdapter(reader),
        PostgreSQLGovernedDocumentTerminologyAdapter(PostgreSQLTerminologyRepository(owner)), evidence_query, lifecycle,
        CanonicalDocumentCitationAdapter(evidence_query, scientific_query), PostgreSQLRecommendationRepository(reader),
        PostgreSQLOrthopedicAssessmentRepository(reader), InMemoryDocumentTemplateRepository(canonical_templates()),
        documents, PostgreSQLDocumentAuditAdapter(writer2), review, clock=lambda:SCI_NOW)

    with binder.bind_tenant(current):
        persisted_input = PostgreSQLClinicalReasoningInputRepository(reader).latest(patient)
        exact_guideline=PostgreSQLRecommendationRepository(reader).get_exact(guideline_reference)
        assert exact_guideline==guideline_set
        exact_orthopedic=PostgreSQLOrthopedicAssessmentRepository(reader).get_exact(orthopedic_reference)
        assert exact_orthopedic==orthopedic_set
        generated = engine.generate_controlled(persisted_input, DocumentType.PROCEDURE_JUSTIFICATION_DRAFT,guideline_set_reference=guideline_reference,orthopedic_set_reference=orthopedic_reference)
    assert generated.document.validation.valid and generated.document.status is DocumentStatus.DRAFT
    assert all(entry.source_references for entry in generated.document.traceability.entries[:-1])
    evidence_ref = next(section.evidence[0] for section in generated.document.sections if section.evidence)
    assert evidence_ref.citation_reference_id == citation.citation_record_id and evidence_ref.canonical_vancouver == vancouver.rendered_text

    stream, original_identity = generated.document_stream_id, id(generated)
    del generated, engine, documents, evidence_query, scientific_query, package_query, reader, writer2
    restarted_reader = create_tenant_runtime_engine(url, runtime_role="jmorais_application_reader")
    with binder.bind_tenant(current):
        reread = PostgreSQLMedicalDocumentRepository(restarted_reader).latest(stream)
        stored_reference=reread.document.guideline_recommendation_set_reference
        reconstructed=PostgreSQLRecommendationRepository(restarted_reader).get_exact(stored_reference)
        stored_orthopedic_reference=reread.document.orthopedic_assessment_set_reference
        reconstructed_orthopedic=PostgreSQLOrthopedicAssessmentRepository(restarted_reader).get_exact(stored_orthopedic_reference)
    assert reread is not None and id(reread) != original_identity and reread.version == 1 and reread.previous_version_id is None
    assert reread.document.template_version == "1.0" and reread.document.validation.valid
    assert reread.document.review_status.value == "PENDING_REVIEW" and reread.document.traceability.entries
    assert stored_reference==guideline_reference and reconstructed==guideline_set
    assert stored_orthopedic_reference==orthopedic_reference and reconstructed_orthopedic==orthopedic_set
    assert reread.orthopedic_lineage_status.value=="EXACT"
    assert tuple(x.recommendation_id for x in reconstructed.recommendations)==reread.document.guideline_recommendation_ids
    assert next(section.evidence[0] for section in reread.document.sections if section.evidence).canonical_vancouver == vancouver.rendered_text
    with binder.bind_tenant(other): assert PostgreSQLMedicalDocumentRepository(restarted_reader).latest(stream) is None
    with binder.bind_tenant(other):
        with pytest.raises(Exception): PostgreSQLOrthopedicAssessmentRepository(restarted_reader).get_exact(orthopedic_reference)
    assert PostgreSQLMedicalDocumentRepository(restarted_reader).latest(stream) is None
    with pytest.raises(Exception): PostgreSQLOrthopedicAssessmentRepository(restarted_reader).get_exact(orthopedic_reference)
    with pytest.raises(DBAPIError), owner.begin() as connection:
        connection.execute(text("UPDATE medical_document_versions SET status='ALTERED' WHERE document_stream_id=:s"), {"s":stream})
    with pytest.raises(DBAPIError), owner.begin() as connection:
        connection.execute(text("DELETE FROM medical_document_versions WHERE document_stream_id=:s"), {"s":stream})
    with pytest.raises(DBAPIError), owner.begin() as connection:
        connection.execute(text("UPDATE orthopedic_assessment_set_references SET policy_version='ALTERED' WHERE reference_id=:id"), {"id":orthopedic_reference.reference_id})
    with pytest.raises(DBAPIError), owner.begin() as connection:
        connection.execute(text("DELETE FROM orthopedic_assessment_set_references WHERE reference_id=:id"), {"id":orthopedic_reference.reference_id})
    restarted_reader.dispose(); writer.dispose(); owner.dispose()
