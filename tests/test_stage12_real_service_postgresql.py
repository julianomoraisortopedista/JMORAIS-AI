import os
from dataclasses import replace
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from jmoraIs.application import ScientificEvidencePackagePort
from jmoraIs.appraisal import ClinicalAppraisalPersistenceService, ClinicalAppraisalService, GovernedEvidenceService
from jmoraIs.appraisal.persistence import SQLAlchemyGovernedEvidenceRepository
from jmoraIs.audit_defense import (
    AuditDefenseEventType, AuditDefenseService, CanonicalGovernedAuditEvidenceAdapter,
    PostgreSQLAuditDefenseEventAdapter, PostgreSQLAuditDefenseRepository,
    PostgreSQLGovernedAuditClinicalStateAdapter, PostgreSQLGovernedAuditGuidelineAdapter,
    PostgreSQLGovernedAuditTerminologyAdapter,
)
from jmoraIs.audit_defense.persistence import AuditDefenseJsonCodec
from jmoraIs.clinical import (
    AuthorizedRecommendationReviewService, GovernedEvidenceReevaluationService,
    InMemoryGovernedDecisionAuditRepository, InMemoryReviewerAuthorizationAdapter,
    ReviewAuthorizationPolicy, ReviewerIdentity, ReviewerRole,
)
from jmoraIs.clinical.governance_persistence import SQLAlchemyGovernedEvidenceLifecycleRepository
from jmoraIs.clinical_state.persistence import PostgreSQLClinicalStateRepository
from jmoraIs.evidence_ledger import hash_payload
from jmoraIs.guideline_engine import (
    GovernedGuidelineSourceService, GuidelineRecommendationEngine,
    PostgreSQLGuidelineSourceRepository, PostgreSQLRecommendationAuditAdapter,
    PostgreSQLRecommendationRepository, RecommendationIntent,
)
from jmoraIs.infrastructure.appraisal_persistence import PostgreSQLClinicalAppraisalRepository
from jmoraIs.infrastructure.postgresql_package_catalog import PostgreSQLCanonicalLedger, PostgreSQLPackageCatalogRepository
from jmoraIs.infrastructure.tenant_database import create_tenant_runtime_engine
from jmoraIs.orthopedic_intelligence import (
    PostgreSQLGovernedOrthopedicStateQueryAdapter, PostgreSQLOrthopedicAssessmentRepository,
    PostgreSQLOrthopedicAuditAdapter, OrthopedicIntelligenceService,
)
from jmoraIs.reasoning_input import (
    ClinicalReasoningInputService, EvidenceDirection, EvidenceReferenceSummary,
    PostgreSQLClinicalReasoningInputRepository, PostgreSQLReasoningInputAuditAdapter,
)
from jmoraIs.tenancy.context import TenantContextBinder
from jmoraIs.tenancy.domain import TenantContext
from jmoraIs.terminology import (
    ClinicalTerminologyService, CodeSystem, DeterministicUcumAdapter, MappingReviewStatus,
    MappingType, PostgreSQLTerminologyAuditAdapter, PostgreSQLTerminologyMappingGovernanceRepository,
    PostgreSQLTerminologyRepository, TerminologyMappingGovernanceService,
)
from tests.test_clinical_appraisal_domain import TODAY, request
from tests.test_clinical_state import rich_context, service as clinical_state_service
from tests.test_evidence_package_boundary import NOW, verified_article
from tests.test_guideline_engine import guideline
from tests.test_reasoning_input import evidence as evidence_reference, draft as reasoning_draft, guideline as guideline_reference
from tests.test_terminology import concept, version as terminology_release

pytestmark = pytest.mark.integration


def _context(tenant, organization, correlation):
    return TenantContext(tenant, organization, "stage12-service", "INTERNAL_SERVICE",
                         "CLINICAL_VALIDATION", "stage12-policy", correlation)


def _review_service():
    return AuthorizedRecommendationReviewService(
        InMemoryReviewerAuthorizationAdapter((ReviewerIdentity("stage12-reviewer", ReviewerRole.SENIOR_REVIEWER),)),
        InMemoryGovernedDecisionAuditRepository(), ReviewAuthorizationPolicy(), clock=lambda: NOW)


def test_complete_stage12_real_service_restart_rls_and_traceability():
    url = os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    config = Config("alembic.ini"); config.set_main_option("sqlalchemy.url", url); command.upgrade(config, "head")
    suffix = uuid4().hex; owner = create_engine(url, future=True); binder = TenantContextBinder()
    tenant, organization = f"stage12-{suffix}", f"org-stage12-{suffix}"
    current = _context(tenant, organization, f"corr-{suffix}")
    other = _context(f"other-{suffix}", f"other-org-{suffix}", f"other-corr-{suffix}")
    with owner.begin() as connection:
        connection.execute(text("INSERT INTO tenants(tenant_id,organization_id,display_name,status,policy_version,created_at) VALUES(:t,:o,'Stage 12 complete','ACTIVE','stage12-policy',:at)"), {"t": tenant, "o": organization, "at": NOW})

    patient_id = "pt_" + suffix * 2
    context = rich_context(identifier=f"context-{suffix}")
    context = replace(context, patient_identity=replace(context.patient_identity, patient_id=patient_id),
                      timeline=replace(context.timeline, patient_id=patient_id))
    state_service, _, _ = clinical_state_service((context,))
    state = state_service.build_current_state(patient_id)
    writer = create_tenant_runtime_engine(url, runtime_role="jmorais_application_writer")
    with binder.bind_tenant(current):
        PostgreSQLClinicalStateRepository(writer).append(state)

    term_version = f"terms-{suffix}"
    terminology = PostgreSQLTerminologyRepository(owner)
    release = replace(terminology_release(), version=term_version, version_id=f"version-{suffix}")
    terminology.append(release.version_id, release)
    terms = {"knee pain", "recorded medication", "knee", "LEFT", "locking", "0-110", "varus", "documented", "supplied finding"}
    governance = PostgreSQLTerminologyMappingGovernanceRepository(owner)
    terminology_service = ClinicalTerminologyService(
        terminology, PostgreSQLTerminologyAuditAdapter(owner), DeterministicUcumAdapter(), clock=lambda: NOW)
    for index, term in enumerate(sorted(terms)):
        item = concept(term, term=term, synonyms=(), code_value=f"ORTHO:STAGE12:{index}")
        item = replace(item, version=term_version, codes=(replace(item.codes[0], version=term_version),))
        terminology.append(item.canonical_id, item)
        mapped = terminology_service.resolve_concepts(term, CodeSystem.ORTHOPEDIC, term_version,
                                                      actor_id="stage12-terminology")
        TerminologyMappingGovernanceService(governance, clock=lambda: NOW).persist(
            mapped, source_reference=f"stage12:{term}", target_concept_id=item.canonical_id,
            mapping_type=MappingType.EXACT, review_status=MappingReviewStatus.AUTO_MAPPED,
            review_required=False, mapping_method="deterministic-canonical-match",
            policy_version="terminology-mapping-v1")

    article = verified_article(); article.article_id = f"article-stage12-{suffix}"
    ledger = PostgreSQLCanonicalLedger(owner)
    claim = ledger.create_claim("Synthetic complete Stage 12 evidence", claim_id=f"claim-stage12-{suffix}", created_at=NOW)
    support_ids = []
    for direction in ("supporting", "opposing", "neutral", "inconclusive"):
        _, support, _ = ledger.register_evidence(
            claim_id=claim.claim_id, source_name="NCBI PubMed", source_type="pubmed",
            passage=f"Deterministic {direction} Stage 12 fragment", pmid=article.pmid,
            payload_hash=hash_payload({"article": article.article_id, "direction": direction}),
            retrieved_at=NOW, verification_version="ST-02", pipeline_version="ST-04",
            policy_version="ST-02", support_direction=direction, occurred_at=NOW)
        support_ids.append(support.support_id)
    packages = ScientificEvidencePackagePort(catalog=PostgreSQLPackageCatalogRepository(owner), clock=lambda: NOW)
    package = packages.issue(article=article, ledger=ledger, claim_id=claim.claim_id,
                             support_ids=tuple(support_ids), pipeline_version="ST-04")
    appraisal_repository = PostgreSQLClinicalAppraisalRepository(owner)
    appraisal_service = ClinicalAppraisalPersistenceService(
        ClinicalAppraisalService(packages), appraisal_repository, clock=lambda: NOW)
    appraisal = appraisal_service.assess_and_persist(
        (request(identifier=f"appraisal-stage12-{suffix}", package_id=package.package_id),), as_of=TODAY)[0][0]
    with binder.bind_tenant(current):
        governed = GovernedEvidenceService(
            packages, SQLAlchemyGovernedEvidenceRepository(writer), appraisals=appraisal_repository,
            clock=lambda: NOW).issue_persisted(appraisal.appraisal_id)

    first_guideline_id, second_guideline_id = f"guideline-a-{suffix}", f"guideline-b-{suffix}"
    draft = reasoning_draft(subject_reference=patient_id)
    governed_ref = replace(evidence_reference(governed.governed_evidence_id, package.package_id,
                                              EvidenceDirection.SUPPORTING), recorded_at=NOW)
    package_ref = replace(draft.evidence_packages[0], reference_id=package.package_id)
    guideline_refs = (
        replace(guideline_reference(first_guideline_id), guideline_version="2026.1"),
        replace(guideline_reference(second_guideline_id), guideline_version="2026.1", organization="Other Society"),
    )
    draft = replace(
        draft, patient_clinical_state=replace(draft.patient_clinical_state,
            reference_id=state.state_id, patient_context_version=state.patient_context_version,
            clinical_state_version=state.state_version), terminology_version=term_version,
        evidence=EvidenceReferenceSummary(supporting=(governed_ref,)), evidence_packages=(package_ref,),
        applicable_guidelines=guideline_refs)
    reasoning_service = ClinicalReasoningInputService(
        PostgreSQLClinicalReasoningInputRepository(writer), PostgreSQLReasoningInputAuditAdapter(writer), clock=lambda: NOW)
    with binder.bind_tenant(current):
        reasoning_service.build(draft, actor_id="stage12", source_reference="canonical-persisted-inputs")
        reasoning = reasoning_service.mark_reviewed(patient_id, actor_id="stage12-reviewer", source_reference="review:stage12")

    source_repository = PostgreSQLGuidelineSourceRepository(owner)
    first = replace(guideline(first_guideline_id, f"guideline-rec-a-{suffix}"),
        governed_evidence_ids=(governed.governed_evidence_id,), terminology_version=term_version,
        policy_version=reasoning.policy_versions[0].policy_version)
    second = replace(guideline(second_guideline_id, f"guideline-rec-b-{suffix}"),
        organization="Other Society", intent=RecommendationIntent.AVOID,
        governed_evidence_ids=(governed.governed_evidence_id,), terminology_version=term_version,
        policy_version=reasoning.policy_versions[0].policy_version)
    source_service = GovernedGuidelineSourceService(source_repository, clock=lambda: NOW)
    source_service.persist(first, appraisal_reference=appraisal.appraisal_id, governance_status="ACTIVE")
    source_service.persist(second, appraisal_reference=appraisal.appraisal_id, governance_status="ACTIVE")
    lifecycle = GovernedEvidenceReevaluationService(
        packages, SQLAlchemyGovernedEvidenceLifecycleRepository(writer), policy_version=governed.policy_version,
        appraisal_version=governed.appraisal_version, clock=lambda: NOW)
    with binder.bind_tenant(current):
        recommendation_repository = PostgreSQLRecommendationRepository(writer)
        guideline_set = GuidelineRecommendationEngine(
            source_repository, SQLAlchemyGovernedEvidenceRepository(writer), lifecycle, terminology,
            recommendation_repository, PostgreSQLRecommendationAuditAdapter(writer), _review_service(),
            clock=lambda: NOW).create_recommendation_set(reasoning)

        state_query = PostgreSQLGovernedOrthopedicStateQueryAdapter(writer, terminology_service, term_version)
        audit_terms = PostgreSQLGovernedAuditTerminologyAdapter(
            terminology, governance, policy_version="terminology-mapping-v1")
        orthopedic_repository = PostgreSQLOrthopedicAssessmentRepository(writer)
        orthopedic = OrthopedicIntelligenceService(
            state_query, SQLAlchemyGovernedEvidenceRepository(writer), lifecycle, recommendation_repository,
            audit_terms, orthopedic_repository, PostgreSQLOrthopedicAuditAdapter(writer), _review_service(),
            clock=lambda: NOW).generate(reasoning)
    assert guideline_set.recommendations and orthopedic.assessment.joints

    writer.dispose(); del writer, state_service, reasoning_service, terminology_service, recommendation_repository, orthopedic_repository

    reader = create_tenant_runtime_engine(url, runtime_role="jmorais_application_reader")
    defense_writer = create_tenant_runtime_engine(url, runtime_role="jmorais_application_writer")
    restarted_owner = create_engine(url, future=True)
    package_query = ScientificEvidencePackagePort(
        catalog=PostgreSQLPackageCatalogRepository(restarted_owner), clock=lambda: NOW)
    appraisal_query = ClinicalAppraisalPersistenceService(
        ClinicalAppraisalService(package_query), PostgreSQLClinicalAppraisalRepository(restarted_owner), clock=lambda: NOW)
    lifecycle_writer = create_tenant_runtime_engine(url, runtime_role="jmorais_application_writer")
    restarted_lifecycle = GovernedEvidenceReevaluationService(
        package_query, SQLAlchemyGovernedEvidenceLifecycleRepository(lifecycle_writer),
        policy_version=governed.policy_version, appraisal_version=governed.appraisal_version, clock=lambda: NOW)
    evidence_adapter = CanonicalGovernedAuditEvidenceAdapter(
        GovernedEvidenceService(package_query, SQLAlchemyGovernedEvidenceRepository(reader), clock=lambda: NOW),
        restarted_lifecycle, appraisal_query)
    restarted_terms = PostgreSQLGovernedAuditTerminologyAdapter(
        PostgreSQLTerminologyRepository(restarted_owner),
        PostgreSQLTerminologyMappingGovernanceRepository(restarted_owner),
        policy_version="terminology-mapping-v1")
    guideline_adapter = PostgreSQLGovernedAuditGuidelineAdapter(
        PostgreSQLRecommendationRepository(reader), PostgreSQLGuidelineSourceRepository(restarted_owner),
        PostgreSQLClinicalReasoningInputRepository(reader), appraisal_query,
        PostgreSQLTerminologyRepository(restarted_owner), clock=lambda: NOW)
    defense_repository = PostgreSQLAuditDefenseRepository(defense_writer)
    defense_audit = PostgreSQLAuditDefenseEventAdapter(defense_writer)
    with binder.bind_tenant(current):
        reread_reasoning = PostgreSQLClinicalReasoningInputRepository(reader).get(reasoning.input_id)
        clinical_adapter = PostgreSQLGovernedAuditClinicalStateAdapter(reader)
        clinical_facts = clinical_adapter.facts(state.state_id)
        service = AuditDefenseService(
            clinical_adapter, evidence_adapter, restarted_lifecycle,
            guideline_adapter, PostgreSQLOrthopedicAssessmentRepository(reader), restarted_terms,
            defense_repository, defense_audit, _review_service(), clock=lambda: NOW)
        generated = service.generate(reread_reasoning)
        events = defense_audit.history(generated.stream_id)

    directions = generated.defense.explainability
    assert directions.supporting_evidence_ids == directions.opposing_evidence_ids
    assert directions.neutral_evidence_ids == directions.inconclusive_evidence_ids == (governed.governed_evidence_id,)
    assert any(item.code == "OPPOSING_EVIDENCE_PRESENT" for item in generated.defense.arguments[0].counterarguments)
    assert directions.conflict_references and generated.defense.provenance_references
    assert not generated.defense.externally_actionable
    assert clinical_facts and all(item.epistemic_status and item.provenance_references for item in clinical_facts)
    source_fact_ids = {item.fact_id for item in clinical_facts}
    source_guideline_ids = {item.recommendation_id for item in guideline_set.recommendations}
    for argument in generated.defense.arguments:
        assert argument.argument_code == "SOURCE_BOUND_TECHNICAL_ARGUMENT"
        assert {item.fact_id for item in argument.clinical_support} <= source_fact_ids
        assert {item.governed_evidence_id for item in argument.scientific_support} == {governed.governed_evidence_id}
        assert {item.recommendation_id for item in argument.guideline_support} == source_guideline_ids
        assert set(argument.terminology_references) <= terms
    generated_review_status = generated.defense.review_status
    serialized_generated = AuditDefenseJsonCodec().encode(generated)
    event_types = {event.event_type for event in events}
    assert {AuditDefenseEventType.GENERATION, AuditDefenseEventType.EVIDENCE_AGGREGATION,
            AuditDefenseEventType.GUIDELINE_AGGREGATION, AuditDefenseEventType.CONFLICT_EXPOSITION,
            AuditDefenseEventType.LIMITATION_EXPOSITION, AuditDefenseEventType.COUNTERARGUMENT_GENERATION} <= event_types
    assert next(event for event in events if event.event_type is AuditDefenseEventType.GENERATION).decision_code == "REVIEW_REQUIRED"

    defense_writer.dispose(); reader.dispose(); lifecycle_writer.dispose()
    del service, defense_repository, defense_audit, generated
    restarted_reader = create_tenant_runtime_engine(url, runtime_role="jmorais_application_reader")
    restarted_repository = PostgreSQLAuditDefenseRepository(restarted_reader)
    restarted_audit = PostgreSQLAuditDefenseEventAdapter(restarted_reader)
    stream_id = "def_" + __import__("hashlib").sha256("|".join((patient_id, "audit-defense")).encode()).hexdigest()
    with binder.bind_tenant(current):
        reread = restarted_repository.latest(stream_id)
        reread_events = restarted_audit.history(stream_id)
    assert reread is not None and reread.defense.reasoning_input_id == reasoning.input_id
    assert AuditDefenseJsonCodec().encode(reread) == serialized_generated
    assert reread.defense.orthopedic_assessment_set_id == orthopedic.set_id
    assert reread.defense.explainability == directions and reread.defense.review_status == generated_review_status
    assert reread_events == events and reread_events is not events
    with binder.bind_tenant(other):
        assert restarted_repository.latest(reread.stream_id) is None
        assert restarted_audit.history(reread.stream_id) == ()
    assert restarted_repository.latest(reread.stream_id) is None
    assert restarted_audit.history(reread.stream_id) == ()
    with restarted_owner.connect() as connection:
        bypass = connection.execute(text("SELECT rolbypassrls FROM pg_roles WHERE rolname='jmorais_application_reader'" )).scalar_one()
        tenant_value = connection.execute(text("SELECT tenant_id FROM audit_defense_versions WHERE package_id=:id"), {"id": reread.package_id}).scalar_one()
    assert not bypass and tenant_value == tenant
    with pytest.raises(DBAPIError), restarted_owner.begin() as connection:
        connection.execute(text("UPDATE audit_defense_versions SET status='ALTERED' WHERE package_id=:id"), {"id": reread.package_id})
    with pytest.raises(DBAPIError), restarted_owner.begin() as connection:
        connection.execute(text("DELETE FROM audit_defense_versions WHERE package_id=:id"), {"id": reread.package_id})
    with pytest.raises(DBAPIError), restarted_owner.begin() as connection:
        connection.execute(text("DELETE FROM audit_defense_events WHERE stream_id=:id"), {"id": reread.stream_id})
    restarted_reader.dispose(); restarted_owner.dispose(); owner.dispose()
