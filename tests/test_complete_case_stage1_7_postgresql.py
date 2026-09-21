from jmoraIs.medical_documents.exact_reference_persistence import PostgreSQLMedicalDocumentExactReferenceRepository
"""Continuous production-service proof for COMPLETE_CASE stages 1 through 7."""
import hashlib
import os
from dataclasses import replace
from datetime import datetime,timedelta,timezone
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine,text

from evaluation.e2e_acceptance.models import AcceptanceStage,E2ETraceManifest,ExecutionStatus,StageExecution
from evaluation.e2e_acceptance.persistence import PostgreSQLAcceptanceManifestRepository

from jmoraIs.application import ScientificEvidencePackagePort
from jmoraIs.application.scientific_citations import ScientificCitationService
from jmoraIs.appraisal import ClinicalAppraisalPersistenceService,ClinicalAppraisalService,GovernedEvidenceService
from jmoraIs.appraisal.persistence import SQLAlchemyGovernedEvidenceRepository
from jmoraIs.clinical_state.persistence import PostgreSQLClinicalStateRepository
from jmoraIs.clinical import (AuthorizedRecommendationReviewService,GovernedEvidenceReevaluationService,
    InMemoryGovernedDecisionAuditRepository,InMemoryReviewerAuthorizationAdapter,ReviewAuthorizationPolicy,
    ReviewerIdentity,ReviewerRole)
from jmoraIs.clinical.governance_persistence import SQLAlchemyGovernedEvidenceLifecycleRepository
from jmoraIs.evidence_ledger import hash_payload
from jmoraIs.infrastructure.appraisal_persistence import PostgreSQLClinicalAppraisalRepository
from jmoraIs.infrastructure.postgresql_package_catalog import PostgreSQLCanonicalLedger,PostgreSQLPackageCatalogRepository
from jmoraIs.infrastructure.cryptographic_replay import PostgreSQLCryptographicReplayEngine,ReplayIntegrityStatus
from jmoraIs.infrastructure.scientific_citation_persistence import PostgreSQLScientificCitationRepository
from jmoraIs.infrastructure.tenant_database import create_tenant_runtime_engine
from jmoraIs.infrastructure.identity_persistence import PostgreSQLExternalIdentityLinkRepository,PostgreSQLIdentitySecurityAudit
from jmoraIs.infrastructure.oidc_identity import OIDCIdentityProviderAdapter
from jmoraIs.infrastructure.session_persistence import PostgreSQLReplayProtectionRepository,PostgreSQLSessionRepository,PostgreSQLSessionSecurityAudit
from jmoraIs.identity.domain import ExternalIdentityLink,IdentityLinkStatus,PrincipalType
from jmoraIs.identity.configuration import OIDCProviderConfig
from jmoraIs.identity.reviewer import AuthenticatedReviewerResolver
from jmoraIs.identity.session_application import CanonicalSessionSecurityService
from jmoraIs.identity.session_domain import SessionSecurityPolicy
from jmoraIs.infrastructure.managed_attestation import ManagedAttestationFactory,ManagedPersistedGatewayInputVerifier
from jmoraIs.infrastructure.managed_secrets import EphemeralSecretProvider,InMemoryKeyMetadataRepository
from jmoraIs.infrastructure.persisted_gateway_input import PostgreSQLPersistedGatewayInputRepository,PersistedGatewayInputTrustService
from jmoraIs.secrets.domain import KeyReference,KeyState,ManagedKeyMetadata,SecretPurpose,SecretReference
from jmoraIs.governed_llm_draft import GovernedDraftAttestor,GovernedLLMDraftIssuanceService,PostgreSQLGovernedLLMDraftRepository
from jmoraIs.clinical.governance_persistence import PostgreSQLReviewerIdentityRepository
from jmoraIs.llm_human_review import (AuthorizedLLMHumanReviewService,LLMReviewDecision,PostgreSQLLLMHumanReviewRepository,
    PostgreSQLLLMHumanReviewSecurityAudit,UpstreamReviewGovernanceRouter)
from jmoraIs.audit_defense.review_governance import AuditDefenseReviewGovernanceAdapter
from jmoraIs.llm_gateway import (CanonicalLLMGateway,LLMModel,LLMOutputClassification,LLMProvider,LLMRequest,
    MockProviderAdapter,PostgreSQLInvocationRepository,PostgreSQLLLMInvocationContextRepository,
    PostgreSQLPromptAuditRepository,PostgreSQLPromptRepository,PromptGovernanceService,PromptTemplate,ReviewPolicy)
from jmoraIs.guideline_engine import (GovernedGuidelineSourceService,GuidelineRecommendationEngine,
    PostgreSQLGuidelineSourceRepository,PostgreSQLRecommendationAuditAdapter,PostgreSQLRecommendationRepository)
from jmoraIs.orthopedic_intelligence import (OrthopedicIntelligenceService,PostgreSQLGovernedOrthopedicStateQueryAdapter,
    PostgreSQLOrthopedicAssessmentRepository,PostgreSQLOrthopedicAuditAdapter)
from jmoraIs.audit_defense import PostgreSQLGovernedAuditTerminologyAdapter
from jmoraIs.audit_defense import (AuditDefenseService,AuditDefenseTraceabilityService,CanonicalGovernedAuditEvidenceAdapter,
    AuditDefenseGatewayInputIssuer,AuditDefenseGatewayInputResolver,
    PostgreSQLAuditDefenseEventAdapter,PostgreSQLAuditDefenseRepository,PostgreSQLGovernedAuditClinicalStateAdapter,
    PostgreSQLGovernedAuditGuidelineAdapter,PostgreSQLMedicalDocumentTraceAdapter)
from jmoraIs.medical_documents import (CanonicalDocumentCitationAdapter,DocumentType,InMemoryDocumentTemplateRepository,
    MedicalDocumentEngine,PostgreSQLDocumentAuditAdapter,PostgreSQLGovernedDocumentClinicalStateAdapter,
    PostgreSQLGovernedDocumentTerminologyAdapter,PostgreSQLMedicalDocumentRepository,canonical_templates)
from jmoraIs.patient_context.persistence import PostgreSQLAuthorizedClinicalIngestionRepository,PostgreSQLPatientContextRepository
from jmoraIs.tenancy.context import TenantContextBinder
from jmoraIs.tenancy.domain import TenantContext
from jmoraIs.terminology import (ClinicalTerminologyService,CodeSystem,DeterministicUcumAdapter,
    MappingReviewStatus,MappingType,PostgreSQLTerminologyAuditAdapter,
    PostgreSQLTerminologyMappingGovernanceRepository,PostgreSQLTerminologyRepository,
    TerminologyMappingGovernanceService)
from jmoraIs.reasoning_input import (ClinicalReasoningInputService,EvidenceDirection,EvidenceReferenceSummary,
    PostgreSQLClinicalReasoningInputRepository,PostgreSQLReasoningInputAuditAdapter)
from tests.test_authorized_ingestion_persistence_postgresql import compose_service,ingestion_command
from tests.test_clinical_appraisal_domain import TODAY,request
from tests.test_clinical_state import service as clinical_state_service
from tests.test_clinical_state import rich_context
from tests.test_evidence_package_boundary import NOW,verified_article
from tests.test_guideline_engine import guideline
from tests.test_reasoning_input import draft as reasoning_draft,evidence as evidence_reference,guideline as guideline_reference
from tests.test_terminology import concept,version as terminology_release
from jmoraIs.vancouver import StrictVancouverFormatter
from tests.test_llm_gateway import response as llm_response
from tests.test_stage13_real_service_postgresql import _StaticSigningKeys,_oidc_config

pytestmark=pytest.mark.integration

def test_complete_case_1_to_14_persists_restarts_and_traces_exactly():
    url=os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url:pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    config=Config("alembic.ini");config.set_main_option("sqlalchemy.url",url);command.upgrade(config,"head")
    suffix=uuid4().hex;owner=create_engine(url,future=True);binder=TenantContextBinder()
    tenant=TenantContext("complete-"+suffix,"complete-org-"+suffix,"complete-principal-"+suffix,
        "CLINICIAN","CLINICAL_DOCUMENTATION","privacy-v1","corr-complete-"+suffix)
    patient_id="pt_"+hashlib.sha256(suffix.encode()).hexdigest()
    with owner.begin() as c:c.execute(text("INSERT INTO tenants(tenant_id,organization_id,display_name,status,policy_version,created_at) VALUES(:t,:o,'Complete 1-7','ACTIVE','privacy-v1',:at)"),{"t":tenant.tenant_id,"o":tenant.organization_id,"at":NOW})
    writer=create_tenant_runtime_engine(url,runtime_role="jmorais_application_writer")

    # Stage 1 and 2: the transaction-owning ingestion service is the only writer.
    with binder.bind_tenant(tenant):
        ingestion,contexts,records,_,actor=compose_service(writer,patient_id,tenant)
        base_command=ingestion_command(patient_id,actor,suffix)
        rich=rich_context("authorized-context-"+suffix)
        rich=replace(rich,patient_identity=replace(rich.patient_identity,patient_id=patient_id),timeline=replace(rich.timeline,patient_id=patient_id))
        retained=("age_years","clinical_problems","diagnosis_candidates","findings","medications","laboratory_results","imaging_studies","functional_statuses","pain_assessments","risk_factors","current_conditions","orthopedic_contexts")
        typed_payload=tuple(replace(base_command.clinical_payload[0],name=name,value="structured") for name in retained)
        receipt=ingestion.ingest(replace(base_command,context=rich,clinical_payload=typed_payload))
        ingestion_record=records.get(receipt.ingestion_record_id)
        patient_context=contexts.get(ingestion_record.patient_context_id)
    assert patient_context.version==ingestion_record.patient_context_version

    # Stage 3: canonical deterministic projection from the exact persisted context.
    state_service,_,_=clinical_state_service((patient_context,))
    clinical_state=state_service.build_current_state(patient_id)
    with binder.bind_tenant(tenant):PostgreSQLClinicalStateRepository(writer).append(clinical_state)
    assert clinical_state.patient_context_id==patient_context.context_id

    # Stage 4: persisted concept plus owner-governed deterministic mapping.
    term_version="terms-"+suffix;release=replace(terminology_release(),version=term_version,version_id="version-"+suffix)
    terminology=PostgreSQLTerminologyRepository(owner);terminology.append(release.version_id,release)
    terminology_service=ClinicalTerminologyService(terminology,PostgreSQLTerminologyAuditAdapter(owner),DeterministicUcumAdapter(),clock=lambda:NOW)
    governance_repository=PostgreSQLTerminologyMappingGovernanceRepository(owner)
    governance_references=[]
    required_terms=("knee","LEFT","locking","0-110","varus","documented","supplied finding","knee pain","recorded medication")
    for index,source_term in enumerate(required_terms):
        term=replace(concept(source_term,term=source_term,synonyms=(),code_value=f"ORTHO:COMPLETE:{index}"),version=term_version,codes=(replace(concept().codes[0],version=term_version),))
        terminology.append(term.canonical_id,term)
        mapped=terminology_service.resolve_concepts(source_term,CodeSystem.ORTHOPEDIC,term_version,actor_id="complete-terminology")
        governance_record=TerminologyMappingGovernanceService(governance_repository,clock=lambda:NOW).persist(mapped,
            source_reference="complete:"+source_term,target_concept_id=term.canonical_id,mapping_type=MappingType.EXACT,
            review_status=MappingReviewStatus.AUTO_MAPPED,review_required=False,mapping_method="deterministic-canonical-match",policy_version="terminology-mapping-v1")
        governance_references.append(governance_repository.reference_for(governance_record))
    governance_references=tuple(sorted(governance_references,key=lambda item:item.reference_id))

    # Stage 5: real ledger-backed package issuance.
    article=verified_article();article.article_id="article-complete-"+suffix;article.authors=["Doe J"];article.journal="Governed Orthopedic Journal";article.publication_year=2025
    ledger=PostgreSQLCanonicalLedger(owner);claim=ledger.create_claim("Synthetic governed complete-case evidence",claim_id="claim-complete-"+suffix,created_at=NOW)
    _,support,_=ledger.register_evidence(claim_id=claim.claim_id,source_name="NCBI PubMed",source_type="pubmed",
        passage="Deterministic de-identified complete-case evidence",pmid=article.pmid,
        payload_hash=hash_payload({"article":article.article_id}),retrieved_at=NOW,verification_version="ST-02",
        pipeline_version="ST-04",policy_version="ST-02",support_direction="supporting",occurred_at=NOW)
    packages=ScientificEvidencePackagePort(catalog=PostgreSQLPackageCatalogRepository(owner),clock=lambda:NOW)
    package=packages.issue(article=article,ledger=ledger,claim_id=claim.claim_id,support_ids=(support.support_id,),pipeline_version="ST-04")
    vancouver=StrictVancouverFormatter(packages,clock=lambda:NOW).render(package_id=package.package_id,article=article)
    citation=ScientificCitationService(PostgreSQLScientificCitationRepository(owner),packages,clock=lambda:NOW).issue(package_id=package.package_id,article=article,vancouver_reference=vancouver)

    # Stages 6 and 7: persisted appraisal is the sole GovernedEvidence issuance input.
    appraisal_repository=PostgreSQLClinicalAppraisalRepository(owner)
    appraisal_service=ClinicalAppraisalPersistenceService(ClinicalAppraisalService(packages),appraisal_repository,clock=lambda:NOW)
    appraisal=appraisal_service.assess_and_persist((request(identifier="appraisal-complete-"+suffix,package_id=package.package_id),),as_of=TODAY)[0][0]
    with binder.bind_tenant(tenant):
        governed=GovernedEvidenceService(packages,SQLAlchemyGovernedEvidenceRepository(writer),appraisals=appraisal_repository,clock=lambda:NOW).issue_persisted(appraisal.appraisal_id)

    expected=(ingestion_record.ingestion_record_id,patient_context.context_id,clinical_state.state_id,
        governance_references,package.package_id,appraisal.appraisal_id,governed.governed_evidence_id)
    del ingestion,contexts,records,actor,receipt,ingestion_record,patient_context,state_service,clinical_state
    del terminology,terminology_service,mapped,governance_repository,governance_record,ledger,packages,package
    del appraisal_repository,appraisal_service,appraisal,governed
    writer.dispose();owner.dispose()

    # Mandatory intermediate restart: no trusted aggregate survives.
    restarted_owner=create_engine(url,future=True);reader=create_tenant_runtime_engine(url,runtime_role="jmorais_application_reader")
    record_id,context_id,state_id,term_refs,package_id,appraisal_id,governed_id=expected
    with binder.bind_tenant(tenant):
        reread_record=PostgreSQLAuthorizedClinicalIngestionRepository(reader).get(record_id)
        reread_context=PostgreSQLPatientContextRepository(reader).get(context_id)
        reread_state=PostgreSQLClinicalStateRepository(reader).get(state_id)
        reread_governed=SQLAlchemyGovernedEvidenceRepository(reader).get(governed_id)
    restarted_governance=PostgreSQLTerminologyMappingGovernanceRepository(restarted_owner)
    reread_mappings=tuple(restarted_governance.get_exact(item) for item in term_refs)
    reread_package=ScientificEvidencePackagePort(catalog=PostgreSQLPackageCatalogRepository(restarted_owner),clock=lambda:NOW).get(package_id)
    reread_appraisal=PostgreSQLClinicalAppraisalRepository(restarted_owner).get(appraisal_id)
    assert reread_record.patient_context_id==reread_context.context_id==reread_state.patient_context_id
    assert {item.target_concept_id for item in reread_mappings}==set(required_terms)
    assert reread_appraisal.evidence_package_id==reread_package.package_id==reread_governed.evidence_package_id
    assert reread_governed.appraisal_result_id==reread_appraisal.appraisal_id
    assert reread_state.pseudonymous_patient_id==patient_id

    # Stage 8: construct exclusively from the reread Stage 3/4/5/7 references.
    guideline_id="guideline-complete-"+suffix
    base=reasoning_draft(subject_reference=patient_id)
    governed_ref=replace(evidence_reference(governed_id,package_id,EvidenceDirection.SUPPORTING),recorded_at=NOW)
    input_draft=replace(base,
        patient_clinical_state=replace(base.patient_clinical_state,reference_id=state_id,
            patient_context_version=reread_state.patient_context_version,clinical_state_version=reread_state.state_version),
        terminology_version=term_version,evidence=EvidenceReferenceSummary(supporting=(governed_ref,)),
        evidence_packages=(replace(base.evidence_packages[0],reference_id=package_id),),
        applicable_guidelines=(replace(guideline_reference(guideline_id),guideline_version="2026.1"),),
        terminology_governance_references=term_refs)
    reasoning_writer=create_tenant_runtime_engine(url,runtime_role="jmorais_application_writer")
    with binder.bind_tenant(tenant):
        reasoning_repository=PostgreSQLClinicalReasoningInputRepository(reasoning_writer)
        reasoning_service=ClinicalReasoningInputService(reasoning_repository,PostgreSQLReasoningInputAuditAdapter(reasoning_writer),clock=lambda:NOW,terminology_governance=restarted_governance)
        reasoning_service.build(input_draft,actor_id="complete-assembler",source_reference="complete:stage1-7")
        reasoning=reasoning_service.mark_reviewed(patient_id,actor_id="complete-reviewer",source_reference="review:complete")
    reasoning_id,reasoning_version=reasoning.input_id,reasoning.input_version

    # Stage 9: persisted guideline source, deterministic engine, owner-issued exact reference.
    source_repository=PostgreSQLGuidelineSourceRepository(restarted_owner)
    rule=replace(guideline(guideline_id,"guideline-rec-"+suffix),governed_evidence_ids=(governed_id,),
        terminology_version=term_version,policy_version=reasoning.policy_versions[0].policy_version)
    GovernedGuidelineSourceService(source_repository,clock=lambda:NOW).persist(rule,appraisal_reference=appraisal_id,governance_status="ACTIVE")
    packages_after=ScientificEvidencePackagePort(catalog=PostgreSQLPackageCatalogRepository(restarted_owner),clock=lambda:NOW)
    lifecycle_writer=create_tenant_runtime_engine(url,runtime_role="jmorais_application_writer")
    lifecycle=GovernedEvidenceReevaluationService(packages_after,SQLAlchemyGovernedEvidenceLifecycleRepository(lifecycle_writer),
        policy_version=reread_governed.policy_version,appraisal_version=reread_governed.appraisal_version,clock=lambda:NOW)
    review=AuthorizedRecommendationReviewService(InMemoryReviewerAuthorizationAdapter((ReviewerIdentity("complete-reviewer",ReviewerRole.SENIOR_REVIEWER),)),InMemoryGovernedDecisionAuditRepository(),ReviewAuthorizationPolicy(),clock=lambda:NOW)
    with binder.bind_tenant(tenant):
        recommendation_repository=PostgreSQLRecommendationRepository(reasoning_writer)
        guideline_set=GuidelineRecommendationEngine(source_repository,SQLAlchemyGovernedEvidenceRepository(reader),lifecycle,
            PostgreSQLTerminologyRepository(restarted_owner),recommendation_repository,PostgreSQLRecommendationAuditAdapter(reasoning_writer),review,clock=lambda:NOW).create_recommendation_set(reasoning)
        guideline_reference_exact=recommendation_repository.reference_for(guideline_set)

    # Stage 10: persisted orthopedic projection/assessment and owner-issued exact reference.
    with binder.bind_tenant(tenant):
        orthopedic_repository=PostgreSQLOrthopedicAssessmentRepository(reasoning_writer)
        governed_terms=PostgreSQLGovernedAuditTerminologyAdapter(PostgreSQLTerminologyRepository(restarted_owner),restarted_governance,policy_version="terminology-mapping-v1")
        orthopedic=OrthopedicIntelligenceService(PostgreSQLGovernedOrthopedicStateQueryAdapter(reader,ClinicalTerminologyService(PostgreSQLTerminologyRepository(restarted_owner),PostgreSQLTerminologyAuditAdapter(restarted_owner),DeterministicUcumAdapter(),clock=lambda:NOW),term_version),
            SQLAlchemyGovernedEvidenceRepository(reader),lifecycle,recommendation_repository,
            governed_terms,orthopedic_repository,PostgreSQLOrthopedicAuditAdapter(reasoning_writer),review,clock=lambda:NOW).generate(reasoning)
        orthopedic_reference_exact=orthopedic_repository.reference_for(orthopedic)
    assert guideline_set.recommendations and orthopedic.assessment.joints

    # Restart exact handoffs: neither Stage-9 nor Stage-10 aggregate survives.
    guideline_copy,orthopedic_copy=guideline_set,orthopedic
    del reasoning_service,reasoning_repository,reasoning,guideline_set,orthopedic,recommendation_repository,orthopedic_repository
    reader.dispose();reasoning_writer.dispose();lifecycle_writer.dispose();restarted_owner.dispose()
    exact_owner=create_engine(url,future=True);exact_reader=create_tenant_runtime_engine(url,runtime_role="jmorais_application_reader")
    with binder.bind_tenant(tenant):
        exact_reasoning=PostgreSQLClinicalReasoningInputRepository(exact_reader).get(reasoning_id)
        exact_guideline=PostgreSQLRecommendationRepository(exact_reader).get_exact(guideline_reference_exact)
        exact_orthopedic=PostgreSQLOrthopedicAssessmentRepository(exact_reader).get_exact(orthopedic_reference_exact)
    assert exact_guideline==guideline_copy and exact_orthopedic==orthopedic_copy
    assert exact_guideline.reasoning_input_id==exact_reasoning.input_id==exact_orthopedic.assessment.reasoning_input_id

    # Stage 11: both Stage-9 and Stage-10 exact references are mandatory and persisted unchanged.
    document_writer=create_tenant_runtime_engine(url,runtime_role="jmorais_application_writer")
    document_packages=ScientificEvidencePackagePort(catalog=PostgreSQLPackageCatalogRepository(exact_owner),clock=lambda:NOW)
    document_lifecycle=GovernedEvidenceReevaluationService(document_packages,SQLAlchemyGovernedEvidenceLifecycleRepository(document_writer),policy_version=reread_governed.policy_version,appraisal_version=reread_governed.appraisal_version,clock=lambda:NOW)
    evidence_query=SQLAlchemyGovernedEvidenceRepository(exact_reader)
    document_repository=PostgreSQLMedicalDocumentRepository(document_writer)
    document_engine=MedicalDocumentEngine(PostgreSQLGovernedDocumentClinicalStateAdapter(exact_reader),
        PostgreSQLGovernedDocumentTerminologyAdapter(PostgreSQLTerminologyRepository(exact_owner)),evidence_query,document_lifecycle,
        CanonicalDocumentCitationAdapter(evidence_query,ScientificCitationService(PostgreSQLScientificCitationRepository(exact_owner),document_packages,clock=lambda:NOW)),
        PostgreSQLRecommendationRepository(exact_reader),PostgreSQLOrthopedicAssessmentRepository(exact_reader),
        InMemoryDocumentTemplateRepository(canonical_templates()),document_repository,PostgreSQLDocumentAuditAdapter(document_writer),review,clock=lambda:NOW)
    with binder.bind_tenant(tenant):
        document=document_engine.generate_controlled(exact_reasoning,DocumentType.PROCEDURE_JUSTIFICATION_DRAFT,
            guideline_set_reference=guideline_reference_exact,orthopedic_set_reference=orthopedic_reference_exact)
        document_reference=PostgreSQLMedicalDocumentExactReferenceRepository(document_writer,clock=lambda:NOW).reference_for(document)
    assert document.document.guideline_recommendation_set_reference==guideline_reference_exact
    assert document.document.orthopedic_assessment_set_reference==orthopedic_reference_exact
    assert any(item.canonical_vancouver==vancouver.rendered_text for section in document.document.sections for item in section.evidence)
    document_stream=document.document_stream_id
    del document_engine,document_repository,document
    document_writer.dispose();exact_reader.dispose()

    # Stage 12: restart, generate from governed ports, then append exact Stage-11 linkage.
    stage12_reader=create_tenant_runtime_engine(url,runtime_role="jmorais_application_reader");stage12_writer=create_tenant_runtime_engine(url,runtime_role="jmorais_application_writer")
    stage12_packages=ScientificEvidencePackagePort(catalog=PostgreSQLPackageCatalogRepository(exact_owner),clock=lambda:NOW)
    stage12_appraisals=ClinicalAppraisalPersistenceService(ClinicalAppraisalService(stage12_packages),PostgreSQLClinicalAppraisalRepository(exact_owner),clock=lambda:NOW)
    stage12_lifecycle=GovernedEvidenceReevaluationService(stage12_packages,SQLAlchemyGovernedEvidenceLifecycleRepository(stage12_writer),policy_version=reread_governed.policy_version,appraisal_version=reread_governed.appraisal_version,clock=lambda:NOW)
    stage12_evidence=CanonicalGovernedAuditEvidenceAdapter(GovernedEvidenceService(stage12_packages,SQLAlchemyGovernedEvidenceRepository(stage12_reader),clock=lambda:NOW),stage12_lifecycle,stage12_appraisals)
    stage12_terms=PostgreSQLGovernedAuditTerminologyAdapter(PostgreSQLTerminologyRepository(exact_owner),PostgreSQLTerminologyMappingGovernanceRepository(exact_owner),policy_version="terminology-mapping-v1")
    stage12_guidelines=PostgreSQLGovernedAuditGuidelineAdapter(PostgreSQLRecommendationRepository(stage12_reader),PostgreSQLGuidelineSourceRepository(exact_owner),PostgreSQLClinicalReasoningInputRepository(stage12_reader),stage12_appraisals,PostgreSQLTerminologyRepository(exact_owner),clock=lambda:NOW)
    defenses=PostgreSQLAuditDefenseRepository(stage12_writer);defense_events=PostgreSQLAuditDefenseEventAdapter(stage12_writer)
    with binder.bind_tenant(tenant):
        stage12_reasoning=PostgreSQLClinicalReasoningInputRepository(stage12_reader).get(reasoning_id)
        defense=AuditDefenseService(PostgreSQLGovernedAuditClinicalStateAdapter(stage12_reader),stage12_evidence,stage12_lifecycle,
            stage12_guidelines,PostgreSQLOrthopedicAssessmentRepository(stage12_reader),stage12_terms,defenses,defense_events,review,clock=lambda:NOW).generate(stage12_reasoning)
        documents=PostgreSQLMedicalDocumentExactReferenceRepository(stage12_reader);document_trace=PostgreSQLMedicalDocumentTraceAdapter(documents)
        defense_reference=AuditDefenseTraceabilityService(document_trace,defenses,defense_events,clock=lambda:NOW).link_stage11_document(defenses.reference_for_pre_link(defense),document_reference)
        final_defense=defenses.get_exact(defense_reference)
    assert final_defense.stage11_document_reference==document_reference
    defense_stream=final_defense.stream_id
    del defense,final_defense,defenses,document_trace,documents,stage12_reasoning
    stage12_reader.dispose();stage12_writer.dispose()

    # Stage 12 restart proof and full Stage 9/10/11 ancestry from the exact final package.
    trace_reader=create_tenant_runtime_engine(url,runtime_role="jmorais_application_reader")
    with binder.bind_tenant(tenant):
        final_after_restart=PostgreSQLAuditDefenseRepository(trace_reader).get_exact(defense_reference)
        document_after_restart=PostgreSQLMedicalDocumentTraceAdapter(PostgreSQLMedicalDocumentExactReferenceRepository(trace_reader)).get_exact(final_after_restart.stage11_document_reference)
        guideline_after_restart=PostgreSQLRecommendationRepository(trace_reader).get_exact(document_after_restart.document.guideline_recommendation_set_reference)
        orthopedic_after_restart=PostgreSQLOrthopedicAssessmentRepository(trace_reader).get_exact(document_after_restart.document.orthopedic_assessment_set_reference)
    assert final_after_restart.stream_id==defense_stream
    assert guideline_after_restart==guideline_copy and orthopedic_after_restart==orthopedic_copy
    assert guideline_after_restart.reasoning_input_id==orthopedic_after_restart.assessment.reasoning_input_id==document_after_restart.document.reasoning_input_id

    # Stage 13: canonical IAM/session, owner-issued AuditDefense input, Gateway and governed draft.
    principal_id="complete-llm-principal-"+suffix;external_subject="complete-subject-"+suffix
    identity_link=ExternalIdentityLink(principal_id,"stage13-oidc",external_subject,tenant.organization_id,tenant.tenant_id,
        IdentityLinkStatus.ACTIVE,PrincipalType.SERVICE,("CLINICAL_VALIDATION",),("llm:invoke",),None,NOW,NOW,"MIP-10.1")
    PostgreSQLExternalIdentityLinkRepository(exact_owner).create(identity_link)
    auth_now=datetime.now(timezone.utc).replace(microsecond=0);session_writer=create_tenant_runtime_engine(url,runtime_role="jmorais_application_writer")
    sessions=CanonicalSessionSecurityService(PostgreSQLSessionRepository(session_writer),PostgreSQLReplayProtectionRepository(session_writer),
        PostgreSQLSessionSecurityAudit(session_writer),SessionSecurityPolicy(policy_version="MIP-10.1"),clock=lambda:auth_now)
    private=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    token=jwt.encode({"iss":"https://stage13.test","aud":"jmorais-stage13","sub":external_subject,
        "iat":int((auth_now-timedelta(seconds=1)).timestamp()),"exp":int((auth_now+timedelta(minutes=5)).timestamp()),
        "auth_time":int((auth_now-timedelta(seconds=1)).timestamp()),"roles":["svc"],"organization_id":tenant.organization_id,
        "sid":"complete-session-"+suffix,"jti":"complete-jti-"+suffix},private,algorithm="RS256",headers={"kid":"stage13-key","typ":"JWT"})
    authenticated=OIDCIdentityProviderAdapter(_oidc_config(),_StaticSigningKeys(private.public_key()),
        PostgreSQLExternalIdentityLinkRepository(exact_owner),PostgreSQLIdentitySecurityAudit(exact_owner),clock=lambda:auth_now,
        tenant_binding=binder,session_validation=sessions).validate(token,tenant.correlation_id)
    llm_context=TenantContext(tenant.tenant_id,tenant.organization_id,authenticated.principal_id,authenticated.roles[0],
        "CLINICAL_VALIDATION","MIP-10.1",tenant.correlation_id)
    key=KeyReference("test-managed","complete-input-"+suffix,"v1",SecretPurpose.SIGNING_KEY)
    secret=SecretReference("test-managed",key.key_id,SecretPurpose.SIGNING_KEY,"v1")
    secret_provider=EphemeralSecretProvider({(key.key_id,"v1"):(secret,b"complete-case-input-attestation-key-material-32")})
    key_metadata=InMemoryKeyMetadataRepository((ManagedKeyMetadata(key,KeyState.ACTIVE,NOW,NOW,None,None,"MIP-10.1"),))
    input_attestor=ManagedAttestationFactory(secret_provider,key_metadata).gateway_input_attestor(key,actor_id="complete-stage13")
    with binder.bind_tenant(llm_context):
        exact_defense=PostgreSQLAuditDefenseRepository(trace_reader).get_exact(defense_reference)
        trace_port=PostgreSQLMedicalDocumentTraceAdapter(PostgreSQLMedicalDocumentExactReferenceRepository(trace_reader))
        gateway_input=AuditDefenseGatewayInputIssuer(PostgreSQLAuditDefenseRepository(trace_reader),input_attestor,clock=lambda:NOW,key_reference=key,document_trace_port=trace_port).issue_from_package(exact_defense,persisted_reference=defense_reference)
    prompts=PostgreSQLPromptRepository(exact_owner);prompt=PromptGovernanceService(prompts,PostgreSQLPromptAuditRepository(exact_owner),clock=lambda:NOW).register(
        PromptTemplate("complete-template-"+suffix,"Complete governed draft","CLINICAL_VALIDATION",
            "Produce a non-actionable structured draft for human review.",(type(exact_defense.defense).__name__,),"complete-draft-v1","MIP-10.1"),created_by=principal_id)
    gateway_writer=create_tenant_runtime_engine(url,runtime_role="jmorais_application_writer")
    invocation_contexts=PostgreSQLLLMInvocationContextRepository(gateway_writer);invocations=PostgreSQLInvocationRepository(gateway_writer)
    provider=MockProviderAdapter((llm_response(provider_request_id="complete-mock-"+suffix,output_text="Governed complete-case draft for human review"),))
    input_verifier=ManagedPersistedGatewayInputVerifier(secret_provider,key_metadata)
    persisted_inputs=PostgreSQLPersistedGatewayInputRepository(gateway_writer,input_verifier)
    gateway=CanonicalLLMGateway(prompts,PostgreSQLPromptAuditRepository(gateway_writer),invocations,invocation_contexts,(provider,),clock=lambda:NOW,persisted_input_attestor=input_attestor,persisted_inputs=persisted_inputs)
    draft_attestor=GovernedDraftAttestor(b"complete-case-governed-draft-key-material-32")
    drafts=PostgreSQLGovernedLLMDraftRepository(gateway_writer,draft_attestor)
    llm_request=LLMRequest("complete-request-"+suffix,prompt.prompt_version_id,LLMModel(LLMProvider.MOCK,"complete-model","1",1.0,2.0,True,"MIP-10.1"),gateway_input,ReviewPolicy("complete-human-review","MIP-10.1",True,False),.2,7,500,"MIP-10.1",NOW)
    with binder.bind_tenant(llm_context):
        gateway_result=gateway.invoke_persisted(llm_request)
        invocation=invocations.history(llm_request.request_id)[0]
        draft=GovernedLLMDraftIssuanceService(drafts,invocations,invocation_contexts,input_attestor,draft_attestor,clock=lambda:NOW).issue(gateway_input,gateway_result,llm_request.review_policy)
    assert gateway_result.classification is LLMOutputClassification.APPROVED_FOR_REVIEW and not gateway_result.externally_actionable
    invocation_id,draft_id=draft.invocation_id,draft.draft_id
    del final_after_restart,document_after_restart,guideline_after_restart,orthopedic_after_restart
    del exact_defense,trace_port,gateway_input,gateway,gateway_result,invocation,draft,drafts,invocations,invocation_contexts,provider,persisted_inputs,llm_request
    trace_reader.dispose();gateway_writer.dispose();session_writer.dispose()

    stage13_reader=create_tenant_runtime_engine(url,runtime_role="jmorais_application_reader")
    with binder.bind_tenant(llm_context):
        reread_invocation=PostgreSQLInvocationRepository(stage13_reader).history("complete-request-"+suffix)[0]
        reread_draft=PostgreSQLGovernedLLMDraftRepository(stage13_reader,draft_attestor).get(draft_id)
        record=PostgreSQLPersistedGatewayInputRepository(stage13_reader,input_verifier).get_by_invocation(invocation_id)
        resolved=PersistedGatewayInputTrustService(PostgreSQLPersistedGatewayInputRepository(stage13_reader,input_verifier),input_verifier,
            {"AuditDefense":AuditDefenseGatewayInputResolver(PostgreSQLAuditDefenseRepository(stage13_reader),PostgreSQLMedicalDocumentTraceAdapter(PostgreSQLMedicalDocumentExactReferenceRepository(stage13_reader)))}).verify_and_resolve(record.persisted_gateway_input_id)
        defense_after_stage13_restart=PostgreSQLAuditDefenseRepository(stage13_reader).get_exact(defense_reference)
    assert reread_invocation.invocation_id==invocation_id==reread_draft.invocation_id
    assert resolved.dto==defense_after_stage13_restart.defense and reread_draft.upstream_artifact_reference==record.upstream_artifact_reference

    # Stage 14: distinct authenticated HUMAN reviewer and AuditDefense owner governance.
    reviewer_id="complete-reviewer-"+suffix;review_principal="complete-human-"+suffix;review_subject="complete-review-subject-"+suffix
    with exact_owner.begin() as c:c.execute(text("INSERT INTO reviewer_identities(reviewer_id,role,status,active,organization_id,tenant_id,created_at,updated_at,authorization_policy_version) VALUES(:id,'REVIEWER','ACTIVE',true,:org,:tenant,:at,:at,'ST-15.1')"),{"id":reviewer_id,"org":tenant.organization_id,"tenant":tenant.tenant_id,"at":NOW})
    review_link=ExternalIdentityLink(review_principal,"complete-review-oidc",review_subject,tenant.organization_id,tenant.tenant_id,
        IdentityLinkStatus.ACTIVE,PrincipalType.HUMAN,("CLINICAL_VALIDATION",),("clinical:review",),reviewer_id,NOW,NOW,"ST-15.1")
    links=PostgreSQLExternalIdentityLinkRepository(exact_owner);links.create(review_link)
    review_now=datetime.now(timezone.utc).replace(microsecond=0);review_writer=create_tenant_runtime_engine(url,runtime_role="jmorais_application_writer")
    review_sessions=CanonicalSessionSecurityService(PostgreSQLSessionRepository(review_writer),PostgreSQLReplayProtectionRepository(review_writer),PostgreSQLSessionSecurityAudit(review_writer),SessionSecurityPolicy(policy_version="MIP-10.1"),clock=lambda:review_now)
    review_private=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    review_config=OIDCProviderConfig("complete-review-oidc","https://complete-review.test","complete-review-audience","https://complete-review.test/config","https://complete-review.test/jwks",("RS256",),10,("sub","iat","exp","auth_time","roles","organization_id"),"roles","organization_id",(("reviewer","CLINICAL_REVIEWER"),),policy_version="MIP-10.1")
    review_token=jwt.encode({"iss":review_config.issuer,"aud":review_config.audience,"sub":review_subject,
        "iat":int((review_now-timedelta(seconds=1)).timestamp()),"exp":int((review_now+timedelta(minutes=5)).timestamp()),"auth_time":int((review_now-timedelta(seconds=1)).timestamp()),
        "roles":["reviewer"],"organization_id":tenant.organization_id,"sid":"complete-review-session-"+suffix,
        "jti":"complete-review-jti-"+suffix,"token_class":"SINGLE_USE"},review_private,algorithm="RS256",headers={"kid":"complete-review-key","typ":"JWT"})
    review_principal_value=OIDCIdentityProviderAdapter(review_config,_StaticSigningKeys(review_private.public_key()),links,
        PostgreSQLIdentitySecurityAudit(exact_owner),clock=lambda:review_now,tenant_binding=binder,session_validation=review_sessions).validate(review_token,tenant.correlation_id)
    review_context=TenantContext(tenant.tenant_id,tenant.organization_id,review_principal_value.principal_id,review_principal_value.roles[0],"CLINICAL_VALIDATION","MIP-10.1",tenant.correlation_id)
    reviewers=PostgreSQLReviewerIdentityRepository(exact_owner);review_events=PostgreSQLLLMHumanReviewRepository(review_writer);review_audit=PostgreSQLLLMHumanReviewSecurityAudit(review_writer)
    with binder.bind_tenant(review_context):
        review_drafts=PostgreSQLGovernedLLMDraftRepository(stage13_reader,draft_attestor)
        review_service=AuthorizedLLMHumanReviewService(review_drafts,PostgreSQLGovernedLLMDraftRepository(review_writer,draft_attestor),PostgreSQLInvocationRepository(stage13_reader),
            PostgreSQLLLMInvocationContextRepository(stage13_reader),prompts,review_events,AuthenticatedReviewerResolver(links,reviewers),reviewers,
            UpstreamReviewGovernanceRouter({"AuditDefense":AuditDefenseReviewGovernanceAdapter(PostgreSQLAuditDefenseRepository(stage13_reader),PostgreSQLMedicalDocumentTraceAdapter(PostgreSQLMedicalDocumentExactReferenceRepository(stage13_reader)))}),
            draft_attestor,ReviewAuthorizationPolicy("ST-15.1",False,True),clock=lambda:NOW,audit=review_audit)
        review_state=review_service.decide(draft_id=draft_id,draft_version=1,principal=review_principal_value,decision=LLMReviewDecision.APPROVE,justification_reference="REVIEW:complete-case")
    assert review_state.status.value=="APPROVED_BY_REVIEWER" and not review_state.externally_actionable
    del review_service,review_drafts,review_events,review_audit,review_state,review_principal_value
    review_writer.dispose();stage13_reader.dispose()

    # Final restart: canonical review, draft, invocation and upstream package remain resolvable.
    final_reader=create_tenant_runtime_engine(url,runtime_role="jmorais_application_reader")
    with binder.bind_tenant(review_context):
        final_review=PostgreSQLLLMHumanReviewRepository(final_reader).current_state(draft_id,1)
        final_draft=PostgreSQLGovernedLLMDraftRepository(final_reader,draft_attestor).get(draft_id)
        final_invocation=PostgreSQLInvocationRepository(final_reader).history("complete-request-"+suffix)[0]
        final_record=PostgreSQLPersistedGatewayInputRepository(final_reader,input_verifier).get_by_invocation(final_invocation.invocation_id)
        final_package=PostgreSQLAuditDefenseRepository(final_reader).get_exact(defense_reference)
    assert final_review.status.value=="APPROVED_BY_REVIEWER" and not final_review.externally_actionable
    assert final_draft.invocation_id==final_invocation.invocation_id
    assert final_invocation.persisted_gateway_input_id==final_record.persisted_gateway_input_id
    assert final_record.upstream_artifact_reference.artifact_id==final_package.stream_id

    # Exact persisted backward trace: every edge is owner-resolved; no latest/history scan selects a version.
    with binder.bind_tenant(review_context):
        final_resolved=PersistedGatewayInputTrustService(
            PostgreSQLPersistedGatewayInputRepository(final_reader,input_verifier),input_verifier,
            {"AuditDefense":AuditDefenseGatewayInputResolver(
                PostgreSQLAuditDefenseRepository(final_reader),
                PostgreSQLMedicalDocumentTraceAdapter(PostgreSQLMedicalDocumentExactReferenceRepository(final_reader)))},
        ).verify_and_resolve(final_record.persisted_gateway_input_id)
        trace_document=PostgreSQLMedicalDocumentTraceAdapter(
            PostgreSQLMedicalDocumentExactReferenceRepository(final_reader)).get_exact(
                final_package.stage11_document_reference)
        trace_guideline=PostgreSQLRecommendationRepository(final_reader).get_exact(
            trace_document.document.guideline_recommendation_set_reference)
        trace_orthopedic=PostgreSQLOrthopedicAssessmentRepository(final_reader).get_exact(
            trace_document.document.orthopedic_assessment_set_reference)
        trace_reasoning=PostgreSQLClinicalReasoningInputRepository(final_reader).get(
            trace_document.document.reasoning_input_id)
        trace_governed=SQLAlchemyGovernedEvidenceRepository(final_reader).get(
            trace_reasoning.evidence.all[0].reference_id)
        trace_state=PostgreSQLClinicalStateRepository(final_reader).get(
            trace_reasoning.patient_clinical_state.reference_id)
        trace_context=PostgreSQLPatientContextRepository(final_reader).get(trace_state.patient_context_id)
        trace_ingestion=PostgreSQLAuthorizedClinicalIngestionRepository(final_reader).get(record_id)
    trace_appraisal=PostgreSQLClinicalAppraisalRepository(exact_owner).get(trace_governed.appraisal_result_id)
    trace_package=ScientificEvidencePackagePort(
        catalog=PostgreSQLPackageCatalogRepository(exact_owner),clock=lambda:NOW).get(
            trace_appraisal.evidence_package_id)
    trace_mappings=tuple(
        PostgreSQLTerminologyMappingGovernanceRepository(exact_owner).get_exact(reference)
        for reference in trace_reasoning.terminology_governance_references)
    assert final_resolved.dto==final_package.defense
    assert trace_document.version_id==final_package.stage11_document_reference.version_id
    assert trace_guideline.reasoning_input_id==trace_reasoning.input_id==trace_orthopedic.assessment.reasoning_input_id
    assert trace_reasoning.input_id==reasoning_id and trace_reasoning.input_version==reasoning_version
    assert trace_governed.appraisal_result_id==trace_appraisal.appraisal_id
    assert trace_appraisal.evidence_package_id==trace_package.package_id
    assert tuple(item.target_concept_id for item in trace_mappings)==tuple(
        item.target_concept_id for item in reread_mappings)
    assert trace_state.state_id==state_id and trace_context.context_id==context_id
    assert trace_ingestion.patient_context_id==trace_context.context_id

    # Persist the reference-only 14-stage acceptance manifest and prove restart-safe reread.
    with binder.bind_tenant(review_context):
        review_event=PostgreSQLLLMHumanReviewRepository(final_reader).history(draft_id)[-1]
    stages=(
        StageExecution(AcceptanceStage.INGESTION,ExecutionStatus.COMPLETED,record_id,"1",(trace_ingestion.provenance_reference,),NOW),
        StageExecution(AcceptanceStage.PATIENT_CONTEXT,ExecutionStatus.COMPLETED,context_id,str(trace_context.version),tuple(trace_context.provenance),NOW),
        StageExecution(AcceptanceStage.CLINICAL_STATE,ExecutionStatus.COMPLETED,state_id,str(trace_state.state_version),trace_state.provenance_references,NOW),
        StageExecution(AcceptanceStage.TERMINOLOGY,ExecutionStatus.COMPLETED,release.version_id,release.version,tuple(item.reference_id for item in term_refs),NOW),
        StageExecution(AcceptanceStage.EVIDENCE_PACKAGE,ExecutionStatus.COMPLETED,package_id,"1",trace_package.provenance_references,NOW),
        StageExecution(AcceptanceStage.CLINICAL_APPRAISAL,ExecutionStatus.COMPLETED,appraisal_id,str(trace_appraisal.appraisal_version),trace_appraisal.provenance_references,NOW),
        StageExecution(AcceptanceStage.GOVERNED_EVIDENCE,ExecutionStatus.COMPLETED,governed_id,trace_governed.appraisal_version,trace_governed.provenance_references,NOW),
        StageExecution(AcceptanceStage.REASONING_INPUT,ExecutionStatus.COMPLETED,reasoning_id,str(reasoning_version),tuple(item.reference_id for item in trace_reasoning.provenance_references),NOW),
        StageExecution(AcceptanceStage.GUIDELINE,ExecutionStatus.COMPLETED,guideline_reference_exact.reference_id,str(guideline_reference_exact.set_version),(guideline_reference_exact.integrity_hash,),NOW),
        StageExecution(AcceptanceStage.ORTHOPEDIC,ExecutionStatus.COMPLETED,orthopedic_reference_exact.reference_id,str(orthopedic_reference_exact.set_version),(orthopedic_reference_exact.integrity_hash,),NOW),
        StageExecution(AcceptanceStage.DOCUMENT,ExecutionStatus.REVIEW_REQUIRED,trace_document.version_id,str(trace_document.version),trace_document.document.provenance_references,NOW),
        StageExecution(AcceptanceStage.AUDIT_DEFENSE,ExecutionStatus.REVIEW_REQUIRED,defense_reference.reference_id,str(defense_reference.version),(defense_reference.integrity_hash,),NOW),
        StageExecution(AcceptanceStage.LLM_GATEWAY,ExecutionStatus.REVIEW_REQUIRED,final_invocation.invocation_id,"1",(final_record.persisted_gateway_input_id,final_draft.draft_id),NOW),
        StageExecution(AcceptanceStage.HUMAN_REVIEW,ExecutionStatus.COMPLETED,review_event.review_event_id,str(review_event.stream_position),(review_event.integrity_hash,),NOW),
    )
    manifest=E2ETraceManifest("complete-execution-"+suffix,"COMPLETE_CASE",tenant.tenant_id,
        tenant.correlation_id,stages,("privacy-v1","MIP-10.1","ST-15.1"),NOW)
    assert manifest.complete and len({stage.stage for stage in manifest.stages})==14
    manifest_writer=create_tenant_runtime_engine(url,runtime_role="jmorais_application_writer")
    with binder.bind_tenant(review_context):PostgreSQLAcceptanceManifestRepository(manifest_writer).append(manifest)
    manifest_writer.dispose();del manifest
    manifest_reader=create_tenant_runtime_engine(url,runtime_role="jmorais_application_reader")
    with binder.bind_tenant(review_context):reread_manifest=PostgreSQLAcceptanceManifestRepository(manifest_reader).get("complete-execution-"+suffix)
    assert reread_manifest.complete and len(reread_manifest.stages)==14
    with pytest.raises(Exception),exact_owner.begin() as connection:
        connection.execute(text("UPDATE e2e_acceptance_manifests SET case_id='tampered' WHERE execution_id=:id"),{"id":"complete-execution-"+suffix})
    with pytest.raises(Exception),exact_owner.begin() as connection:
        connection.execute(text("DELETE FROM e2e_acceptance_manifests WHERE execution_id=:id"),{"id":"complete-execution-"+suffix})

    replay=PostgreSQLCryptographicReplayEngine(exact_owner).replay_all()
    assert replay.integrity_status is ReplayIntegrityStatus.VALID
    assert replay.overall_decision is ReplayIntegrityStatus.VALID
    assert all(stream.completeness_verified for stream in replay.streams)

    other=TenantContext("other-"+suffix,"other-org-"+suffix,"other","CLINICIAN","CLINICAL_DOCUMENTATION","privacy-v1","other-corr-"+suffix)
    with exact_owner.begin() as c:c.execute(text("INSERT INTO tenants(tenant_id,organization_id,display_name,status,policy_version,created_at) VALUES(:t,:o,'Other','ACTIVE','privacy-v1',:at)"),{"t":other.tenant_id,"o":other.organization_id,"at":NOW})
    with binder.bind_tenant(other):
        assert PostgreSQLPatientContextRepository(final_reader).get(context_id) is None
        assert PostgreSQLClinicalStateRepository(final_reader).get(state_id) is None
        assert SQLAlchemyGovernedEvidenceRepository(final_reader).get(governed_id) is None
        with pytest.raises(Exception):PostgreSQLRecommendationRepository(final_reader).get_exact(guideline_reference_exact)
        with pytest.raises(Exception):PostgreSQLOrthopedicAssessmentRepository(final_reader).get_exact(orthopedic_reference_exact)
        with pytest.raises(Exception):PostgreSQLAuditDefenseRepository(final_reader).get_exact(defense_reference)
        assert PostgreSQLLLMHumanReviewRepository(final_reader).current_state(draft_id,1) is None
        assert PostgreSQLAcceptanceManifestRepository(manifest_reader).get("complete-execution-"+suffix) is None
    manifest_reader.dispose();final_reader.dispose();exact_owner.dispose()
