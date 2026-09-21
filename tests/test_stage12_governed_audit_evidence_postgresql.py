import os
from dataclasses import replace
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from jmoraIs.appraisal import (
    ClinicalAppraisalPersistenceService, ClinicalAppraisalService, GovernedEvidenceService,
    SQLAlchemyGovernedEvidenceRepository,
)
from jmoraIs.audit_defense import AuditDefenseBoundaryRejected, CanonicalGovernedAuditEvidenceAdapter
from jmoraIs.clinical import GovernedEvidenceReevaluationService
from jmoraIs.clinical.governance_persistence import SQLAlchemyGovernedEvidenceLifecycleRepository
from jmoraIs.evidence_ledger import hash_payload
from jmoraIs.infrastructure.appraisal_persistence import PostgreSQLClinicalAppraisalRepository
from jmoraIs.infrastructure.postgresql_package_catalog import PostgreSQLCanonicalLedger, PostgreSQLPackageCatalogRepository
from jmoraIs.infrastructure.tenant_database import create_tenant_runtime_engine
from jmoraIs.application import ScientificEvidencePackagePort
from jmoraIs.tenancy.context import TenantContextBinder
from jmoraIs.tenancy.domain import TenantContext
from tests.test_audit_defense import setup as audit_setup
from tests.test_clinical_appraisal_domain import TODAY, request
from tests.test_evidence_package_boundary import NOW, verified_article
from tests.test_guideline_engine import ready_input


pytestmark = pytest.mark.integration


def _context(tenant, organization, correlation):
    return TenantContext(tenant, organization, "stage12-service", "INTERNAL_SERVICE",
                         "CLINICAL_VALIDATION", "stage12-policy", correlation)


def test_restart_rls_and_actual_audit_defense_scientific_support_path():
    url = os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url: pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    config = Config("alembic.ini"); config.set_main_option("sqlalchemy.url", url); command.upgrade(config, "head")
    suffix = uuid4().hex; owner = create_engine(url, future=True)
    tenant, organization = f"audit-evidence-{suffix}", f"org-audit-evidence-{suffix}"
    current = _context(tenant, organization, f"corr-{suffix}")
    other = _context(f"other-{suffix}", f"other-org-{suffix}", f"other-corr-{suffix}")
    with owner.begin() as connection:
        connection.execute(text("INSERT INTO tenants(tenant_id,organization_id,display_name,status,policy_version,created_at) VALUES(:t,:o,'Stage 12','ACTIVE','stage12-policy',:at)"), {"t":tenant,"o":organization,"at":NOW})

    article = verified_article(); article.article_id = f"article-audit-{suffix}"
    ledger = PostgreSQLCanonicalLedger(owner)
    claim = ledger.create_claim("Synthetic Stage 12 evidence", claim_id=f"claim-audit-{suffix}", created_at=NOW)
    _, support, _ = ledger.register_evidence(
        claim_id=claim.claim_id, source_name="NCBI PubMed", source_type="pubmed",
        passage="Deterministic governed evidence", pmid=article.pmid,
        payload_hash=hash_payload({"article":article.article_id}), retrieved_at=NOW,
        verification_version="ST-02", pipeline_version="ST-04", policy_version="ST-02",
        support_direction="supporting", occurred_at=NOW,
    )
    packages = ScientificEvidencePackagePort(catalog=PostgreSQLPackageCatalogRepository(owner), clock=lambda: NOW)
    package = packages.issue(article=article, ledger=ledger, claim_id=claim.claim_id,
                             support_ids=(support.support_id,), pipeline_version="ST-04")
    source = request(identifier=f"recommendation-{suffix}", package_id=package.package_id)
    appraisal_repository = PostgreSQLClinicalAppraisalRepository(owner)
    appraisal_service = ClinicalAppraisalPersistenceService(
        ClinicalAppraisalService(packages), appraisal_repository, clock=lambda: NOW,
    )
    appraisal = appraisal_service.assess_and_persist((source,), as_of=TODAY)[0][0]
    binder = TenantContextBinder(); writer = create_tenant_runtime_engine(url, runtime_role="jmorais_application_writer")
    with binder.bind_tenant(current):
        evidence = GovernedEvidenceService(
            packages, SQLAlchemyGovernedEvidenceRepository(writer), appraisals=appraisal_repository,
            clock=lambda: NOW,
        ).issue_persisted(appraisal.appraisal_id)
    writer.dispose(); del writer, packages, appraisal_service, appraisal_repository, ledger

    restarted_owner = create_engine(url, future=True)
    package_query = ScientificEvidencePackagePort(
        catalog=PostgreSQLPackageCatalogRepository(restarted_owner), clock=lambda: NOW,
    )
    reader = create_tenant_runtime_engine(url, runtime_role="jmorais_application_reader")
    lifecycle_writer = create_tenant_runtime_engine(url, runtime_role="jmorais_application_writer")
    governed_query = GovernedEvidenceService(package_query, SQLAlchemyGovernedEvidenceRepository(reader), clock=lambda: NOW)
    appraisal_query = ClinicalAppraisalPersistenceService(
        ClinicalAppraisalService(package_query), PostgreSQLClinicalAppraisalRepository(restarted_owner), clock=lambda: NOW,
    )
    lifecycle = GovernedEvidenceReevaluationService(
        package_query, SQLAlchemyGovernedEvidenceLifecycleRepository(lifecycle_writer),
        policy_version=evidence.policy_version, appraisal_version=evidence.appraisal_version, clock=lambda: NOW,
    )
    adapter = CanonicalGovernedAuditEvidenceAdapter(governed_query, lifecycle, appraisal_query)
    with binder.bind_tenant(current): reread = adapter.get(evidence.governed_evidence_id)
    assert reread == evidence and reread is not evidence
    assert reread.support_directions == ("SUPPORTING",) and reread.provenance_references and reread.ledger_references
    with binder.bind_tenant(other), pytest.raises(AuditDefenseBoundaryRejected): adapter.get(evidence.governed_evidence_id)
    with pytest.raises(AuditDefenseBoundaryRejected): adapter.get(evidence.governed_evidence_id)

    reasoning = ready_input()
    governed_ref = replace(reasoning.evidence.supporting[0], reference_id=evidence.governed_evidence_id,
                           evidence_package_reference_id=evidence.evidence_package_id)
    package_ref = replace(reasoning.evidence_packages[0], reference_id=evidence.evidence_package_id)
    reasoning = replace(reasoning, evidence_packages=(package_ref,),
                        evidence=replace(reasoning.evidence, supporting=(governed_ref,)))
    service, _, _, _ = audit_setup(evidences=(evidence,), input_value=reasoning)
    service._evidence = adapter; service._lifecycle = lifecycle
    with binder.bind_tenant(current): scientific = service._scientific_support(reasoning)
    assert len(scientific) == 1 and scientific[0].governed_evidence_id == evidence.governed_evidence_id
    assert scientific[0].direction.value == "SUPPORTING"
    reader.dispose(); lifecycle_writer.dispose(); restarted_owner.dispose(); owner.dispose()
