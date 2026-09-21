import os
from dataclasses import replace
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from jmoraIs.appraisal import ClinicalAppraisalPersistenceService, ClinicalAppraisalService, GovernedEvidenceService
from jmoraIs.appraisal.persistence import SQLAlchemyGovernedEvidenceRepository
from jmoraIs.application import ScientificEvidencePackagePort
from jmoraIs.audit_defense import AuditDefenseBoundaryRejected, PostgreSQLGovernedAuditGuidelineAdapter
from jmoraIs.clinical import (
    AuthorizedRecommendationReviewService, GovernedEvidenceReevaluationService,
    InMemoryGovernedDecisionAuditRepository, InMemoryReviewerAuthorizationAdapter,
    ReviewerIdentity, ReviewerRole, ReviewAuthorizationPolicy,
)
from jmoraIs.clinical.governance_persistence import SQLAlchemyGovernedEvidenceLifecycleRepository
from jmoraIs.evidence_ledger import hash_payload
from jmoraIs.guideline_engine import (
    GovernedGuidelineSourceService, GuidelineRecommendationEngine,
    PostgreSQLGuidelineSourceRepository, PostgreSQLRecommendationAuditAdapter,
    PostgreSQLRecommendationRepository,
)
from jmoraIs.infrastructure.appraisal_persistence import PostgreSQLClinicalAppraisalRepository
from jmoraIs.infrastructure.postgresql_package_catalog import PostgreSQLCanonicalLedger, PostgreSQLPackageCatalogRepository
from jmoraIs.infrastructure.tenant_database import create_tenant_runtime_engine
from jmoraIs.reasoning_input import (
    ClinicalReasoningInputService, PostgreSQLClinicalReasoningInputRepository,
    PostgreSQLReasoningInputAuditAdapter,
)
from jmoraIs.tenancy.context import TenantContextBinder
from jmoraIs.tenancy.domain import TenantContext
from jmoraIs.terminology import PostgreSQLTerminologyRepository
from tests.test_audit_defense import setup as audit_setup
from tests.test_clinical_appraisal_domain import TODAY, request
from tests.test_evidence_package_boundary import NOW, verified_article
from tests.test_guideline_engine import guideline
from tests.test_reasoning_input import draft


pytestmark = pytest.mark.integration


def _context(tenant, organization, correlation):
    return TenantContext(tenant, organization, "stage12-service", "INTERNAL_SERVICE",
                         "CLINICAL_VALIDATION", "stage12-policy", correlation)


def test_restart_rls_and_actual_audit_defense_guideline_support_path():
    url = os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url: pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    config = Config("alembic.ini"); config.set_main_option("sqlalchemy.url", url); command.upgrade(config, "head")
    suffix = uuid4().hex; owner = create_engine(url, future=True)
    tenant, organization = f"audit-guideline-{suffix}", f"org-audit-guideline-{suffix}"
    current = _context(tenant, organization, f"corr-{suffix}")
    other = _context(f"other-{suffix}", f"other-org-{suffix}", f"other-corr-{suffix}")
    with owner.begin() as connection:
        connection.execute(text("INSERT INTO tenants(tenant_id,organization_id,display_name,status,policy_version,created_at) VALUES(:t,:o,'Stage 12','ACTIVE','stage12-policy',:at)"), {"t":tenant,"o":organization,"at":NOW})

    article = verified_article(); article.article_id = f"article-guideline-{suffix}"
    ledger = PostgreSQLCanonicalLedger(owner)
    claim = ledger.create_claim("Synthetic guideline evidence", claim_id=f"claim-guideline-{suffix}", created_at=NOW)
    _, support, _ = ledger.register_evidence(
        claim_id=claim.claim_id, source_name="NCBI PubMed", source_type="pubmed",
        passage="Deterministic guideline support", pmid=article.pmid,
        payload_hash=hash_payload({"article":article.article_id}), retrieved_at=NOW,
        verification_version="ST-02", pipeline_version="ST-04", policy_version="ST-02",
        support_direction="supporting", occurred_at=NOW,
    )
    packages = ScientificEvidencePackagePort(catalog=PostgreSQLPackageCatalogRepository(owner), clock=lambda:NOW)
    package = packages.issue(article=article, ledger=ledger, claim_id=claim.claim_id,
                             support_ids=(support.support_id,), pipeline_version="ST-04")
    appraisal_source = request(identifier=f"appraisal-guideline-{suffix}", package_id=package.package_id)
    appraisal_repository = PostgreSQLClinicalAppraisalRepository(owner)
    appraisal_service = ClinicalAppraisalPersistenceService(
        ClinicalAppraisalService(packages), appraisal_repository, clock=lambda:NOW,
    )
    appraisal = appraisal_service.assess_and_persist((appraisal_source,), as_of=TODAY)[0][0]

    binder = TenantContextBinder(); writer = create_tenant_runtime_engine(url, runtime_role="jmorais_application_writer")
    with binder.bind_tenant(current):
        evidence = GovernedEvidenceService(packages, SQLAlchemyGovernedEvidenceRepository(writer),
            appraisals=appraisal_repository, clock=lambda:NOW).issue_persisted(appraisal.appraisal_id)
        reasoning_service = ClinicalReasoningInputService(
            PostgreSQLClinicalReasoningInputRepository(writer), PostgreSQLReasoningInputAuditAdapter(writer), clock=lambda:NOW,
        )
        base = draft(subject_reference="pt_" + suffix * 2)
        package_ref = replace(base.evidence_packages[0], reference_id=package.package_id)
        evidence_ref = replace(base.evidence.supporting[0], reference_id=evidence.governed_evidence_id,
                               evidence_package_reference_id=package.package_id)
        guideline_ref = replace(base.applicable_guidelines[0], reference_id=f"guideline-{suffix}")
        assembled = replace(base, evidence_packages=(package_ref,),
                            evidence=replace(base.evidence, supporting=(evidence_ref,)),
                            applicable_guidelines=(guideline_ref,))
        reasoning_service.build(assembled, actor_id="stage12", source_reference="persisted-inputs")
        reasoning = reasoning_service.mark_reviewed(assembled.subject_reference, actor_id="reviewer",
                                                     source_reference="review:stage12")

    governed_guideline = replace(guideline(identifier=f"guideline-{suffix}"),
        governed_evidence_ids=(evidence.governed_evidence_id,), terminology_version=reasoning.terminology_version,
        policy_version=reasoning.policy_versions[0].policy_version)
    source_repository = PostgreSQLGuidelineSourceRepository(owner)
    source_record = GovernedGuidelineSourceService(source_repository, clock=lambda:NOW).persist(
        governed_guideline, appraisal_reference=appraisal.appraisal_id, governance_status="ACTIVE")
    package_query = ScientificEvidencePackagePort(catalog=PostgreSQLPackageCatalogRepository(owner), clock=lambda:NOW)
    lifecycle = GovernedEvidenceReevaluationService(package_query,
        SQLAlchemyGovernedEvidenceLifecycleRepository(writer), policy_version=evidence.policy_version,
        appraisal_version=evidence.appraisal_version, clock=lambda:NOW)
    review = AuthorizedRecommendationReviewService(
        InMemoryReviewerAuthorizationAdapter((ReviewerIdentity("reviewer", ReviewerRole.SENIOR_REVIEWER),)),
        InMemoryGovernedDecisionAuditRepository(), ReviewAuthorizationPolicy(), clock=lambda:NOW,
    )
    with binder.bind_tenant(current):
        recommendations = PostgreSQLRecommendationRepository(writer)
        generated = GuidelineRecommendationEngine(
            source_repository, SQLAlchemyGovernedEvidenceRepository(writer), lifecycle,
            PostgreSQLTerminologyRepository(owner), recommendations,
            PostgreSQLRecommendationAuditAdapter(writer), review, clock=lambda:NOW,
        ).create_recommendation_set(reasoning)
    writer.dispose(); del writer, reasoning_service, recommendations, source_repository, appraisal_service, ledger

    reader = create_tenant_runtime_engine(url, runtime_role="jmorais_application_reader")
    restarted_owner = create_engine(url, future=True)
    appraisal_query = ClinicalAppraisalPersistenceService(
        ClinicalAppraisalService(package_query), PostgreSQLClinicalAppraisalRepository(restarted_owner), clock=lambda:NOW,
    )
    adapter = PostgreSQLGovernedAuditGuidelineAdapter(
        PostgreSQLRecommendationRepository(reader), PostgreSQLGuidelineSourceRepository(restarted_owner),
        PostgreSQLClinicalReasoningInputRepository(reader), appraisal_query,
        PostgreSQLTerminologyRepository(restarted_owner), clock=lambda:NOW,
    )
    with binder.bind_tenant(current): reread = adapter.latest(reasoning.subject_reference)
    assert reread == generated and reread is not generated
    item = reread.recommendations[0]
    assert item.guideline_id == source_record.guideline_id and item.guideline_version == source_record.source_version_identifier
    assert item.explanation.organization == governed_guideline.organization
    assert item.explanation.strength == governed_guideline.strength
    assert item.explanation.applicability.matched_contexts == ("ADULT",)
    assert item.provenance_references and item.policy_version == governed_guideline.policy_version
    with binder.bind_tenant(other), pytest.raises(AuditDefenseBoundaryRejected): adapter.latest(reasoning.subject_reference)
    with pytest.raises(AuditDefenseBoundaryRejected): adapter.latest(reasoning.subject_reference)

    service, _, _, _ = audit_setup()
    service._guidelines = adapter
    with binder.bind_tenant(current): support_values = service._guideline_support(reasoning)
    assert support_values and support_values[0].guideline_id == governed_guideline.guideline_id
    assert support_values[0].strength == governed_guideline.strength.name
    reader.dispose(); restarted_owner.dispose(); owner.dispose()
