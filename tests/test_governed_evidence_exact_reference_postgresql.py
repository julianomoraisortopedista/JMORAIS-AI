from dataclasses import replace
import os
from uuid import uuid4
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine,text
from sqlalchemy.exc import DBAPIError
from jmoraIs.application import ScientificEvidencePackagePort
from jmoraIs.appraisal import ClinicalAppraisalPersistenceService,ClinicalAppraisalService,GovernedEvidenceService,PostgreSQLGovernedEvidenceExactReferenceRepository
from jmoraIs.appraisal.exact_reference import GovernedEvidenceReferenceRejected,reference_integrity
from jmoraIs.appraisal.persistence import SQLAlchemyGovernedEvidenceRepository
from jmoraIs.clinical import GovernedEvidenceReevaluationService
from jmoraIs.clinical.governance_persistence import SQLAlchemyGovernedEvidenceLifecycleRepository
from jmoraIs.evidence_ledger import hash_payload
from jmoraIs.infrastructure.appraisal_persistence import PostgreSQLClinicalAppraisalRepository
from jmoraIs.infrastructure.cryptographic_replay import PostgreSQLCryptographicReplayEngine,ReplayIntegrityStatus
from jmoraIs.infrastructure.postgresql_package_catalog import PostgreSQLCanonicalLedger,PostgreSQLPackageCatalogRepository
from jmoraIs.infrastructure.tenant_database import create_tenant_runtime_engine
from jmoraIs.tenancy.context import TenantContextBinder
from jmoraIs.tenancy.domain import MissingTenantContext,TenantContext
from tests.test_clinical_appraisal_domain import TODAY,request
from tests.test_evidence_package_boundary import NOW,verified_article

pytestmark=pytest.mark.integration
def database():
    url=os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url:pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    config=Config("alembic.ini");config.set_main_option("sqlalchemy.url",url);command.upgrade(config,"head")
    return url,create_engine(url,future=True)
def setup(owner,writer,suffix,tenant):
    article=verified_article();article.article_id="article-ger-"+suffix
    ledger=PostgreSQLCanonicalLedger(owner);claim=ledger.create_claim("Governed evidence exact reference",claim_id="claim-ger-"+suffix,created_at=NOW)
    _,support,_=ledger.register_evidence(claim_id=claim.claim_id,source_name="NCBI PubMed",source_type="pubmed",passage="Deterministic evidence",pmid=article.pmid,payload_hash=hash_payload({"article":article.article_id}),retrieved_at=NOW,verification_version="ST-02",pipeline_version="ST-04",policy_version="ST-02",support_direction="supporting",occurred_at=NOW)
    packages=ScientificEvidencePackagePort(catalog=PostgreSQLPackageCatalogRepository(owner),clock=lambda:NOW)
    package=packages.issue(article=article,ledger=ledger,claim_id=claim.claim_id,support_ids=(support.support_id,),pipeline_version="ST-04")
    appraisals=PostgreSQLClinicalAppraisalRepository(owner)
    appraisal=ClinicalAppraisalPersistenceService(ClinicalAppraisalService(packages),appraisals,clock=lambda:NOW).assess_and_persist((request(identifier="rec-ger-"+suffix,package_id=package.package_id),),as_of=TODAY)[0][0]
    evidence=GovernedEvidenceService(packages,SQLAlchemyGovernedEvidenceRepository(writer),appraisals=appraisals,clock=lambda:NOW).issue_persisted(appraisal.appraisal_id)
    lifecycle=SQLAlchemyGovernedEvidenceLifecycleRepository(writer)
    GovernedEvidenceReevaluationService(packages,lifecycle,policy_version=evidence.policy_version,appraisal_version=evidence.appraisal_version,clock=lambda:NOW).evaluate(evidence,as_of=TODAY)
    return packages,appraisals,lifecycle,evidence

def test_owner_issuance_restart_exact_reread_rls_append_only_replay_and_lifecycle():
    url,owner=database();suffix=uuid4().hex;tenant=TenantContext("ger-"+suffix,"ger-org-"+suffix,"principal","CLINICIAN","CLINICAL_DOCUMENTATION","ST-02","corr-"+suffix)
    with owner.begin() as c:c.execute(text("INSERT INTO tenants(tenant_id,organization_id,display_name,status,policy_version,created_at) VALUES(:t,:o,'Governed exact','ACTIVE',:p,:at)"),{"t":tenant.tenant_id,"o":tenant.organization_id,"p":tenant.policy_version,"at":NOW})
    writer=create_tenant_runtime_engine(url,runtime_role="jmorais_application_writer");binder=TenantContextBinder()
    with binder.bind_tenant(tenant):
        packages,appraisals,lifecycle,evidence=setup(owner,writer,suffix,tenant)
        repository=PostgreSQLGovernedEvidenceExactReferenceRepository(writer,packages,appraisals,lifecycle,clock=lambda:NOW)
        reference=repository.reference_for(evidence);assert repository.get_exact(reference)==evidence
    del repository,evidence,lifecycle,appraisals,packages;writer.dispose()
    reader=create_tenant_runtime_engine(url,runtime_role="jmorais_application_reader")
    packages=ScientificEvidencePackagePort(catalog=PostgreSQLPackageCatalogRepository(owner),clock=lambda:NOW)
    with binder.bind_tenant(tenant):
        restarted=PostgreSQLGovernedEvidenceExactReferenceRepository(reader,packages,PostgreSQLClinicalAppraisalRepository(owner),SQLAlchemyGovernedEvidenceLifecycleRepository(reader),clock=lambda:NOW)
        reread=restarted.get_exact(reference)
    assert reread.governed_evidence_id==reference.governed_evidence_id and reread.support_directions==("SUPPORTING",)
    other=TenantContext("other-"+suffix,"other-org-"+suffix,"principal","CLINICIAN","CLINICAL_DOCUMENTATION","ST-02","other")
    with owner.begin() as c:c.execute(text("INSERT INTO tenants(tenant_id,organization_id,display_name,status,policy_version,created_at) VALUES(:t,:o,'Other','ACTIVE',:p,:at)"),{"t":other.tenant_id,"o":other.organization_id,"p":other.policy_version,"at":NOW})
    with binder.bind_tenant(other),pytest.raises(GovernedEvidenceReferenceRejected):restarted.get_exact(reference)
    with pytest.raises(MissingTenantContext):restarted.get_exact(reference)
    with pytest.raises(GovernedEvidenceReferenceRejected):restarted.get_exact(reference.governed_evidence_id)
    with pytest.raises(DBAPIError),owner.begin() as c:c.execute(text("UPDATE governed_evidence_persisted_references SET policy_version='tampered' WHERE reference_id=:id"),{"id":reference.reference_id})
    with pytest.raises(DBAPIError),owner.begin() as c:c.execute(text("DELETE FROM governed_evidence_persisted_references WHERE reference_id=:id"),{"id":reference.reference_id})
    assert PostgreSQLCryptographicReplayEngine(owner).replay_governed_evidence_reference(reference.reference_id,tenant_id=tenant.tenant_id).integrity_status is ReplayIntegrityStatus.VALID
    reader.dispose();owner.dispose()

def test_fabricated_linkage_integrity_and_new_inactive_lifecycle_fail_closed():
    url,owner=database();suffix=uuid4().hex;tenant=TenantContext("ger-neg-"+suffix,"ger-neg-org-"+suffix,"principal","CLINICIAN","CLINICAL_DOCUMENTATION","ST-02","corr-neg")
    with owner.begin() as c:c.execute(text("INSERT INTO tenants(tenant_id,organization_id,display_name,status,policy_version,created_at) VALUES(:t,:o,'Governed negative','ACTIVE',:p,:at)"),{"t":tenant.tenant_id,"o":tenant.organization_id,"p":tenant.policy_version,"at":NOW})
    writer=create_tenant_runtime_engine(url,runtime_role="jmorais_application_writer")
    with TenantContextBinder().bind_tenant(tenant):
        packages,appraisals,lifecycle,evidence=setup(owner,writer,suffix,tenant);repository=PostgreSQLGovernedEvidenceExactReferenceRepository(writer,packages,appraisals,lifecycle,clock=lambda:NOW);reference=repository.reference_for(evidence)
        for changes in ({"reference_id":"ger_"+"f"*32},{"evidence_package_id":"wrong"},{"appraisal_record_id":"wrong"},{"tenant_id":"wrong"},{"policy_version":"wrong"},{"provenance_reference":"wrong"},{"governed_evidence_integrity_hash":"f"*64}):
            changed=replace(reference,**changes,integrity_hash="0"*64);changed=replace(changed,integrity_hash=reference_integrity(changed))
            with pytest.raises(GovernedEvidenceReferenceRejected):repository.get_exact(changed)
        GovernedEvidenceReevaluationService(packages,lifecycle,policy_version="changed",appraisal_version=evidence.appraisal_version,clock=lambda:NOW).evaluate(evidence,as_of=TODAY)
        with pytest.raises(GovernedEvidenceReferenceRejected,match="ACTIVE"):repository.get_exact(reference)
    writer.dispose();owner.dispose()
