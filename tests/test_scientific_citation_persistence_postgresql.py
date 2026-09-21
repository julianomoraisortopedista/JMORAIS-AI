import os
from dataclasses import replace
from uuid import uuid4
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine,text
from jmoraIs.application.evidence_packages import ScientificEvidencePackagePort
from jmoraIs.application.scientific_citations import ScientificCitationService
from jmoraIs.evidence_ledger import hash_payload
from jmoraIs.infrastructure.postgresql_package_catalog import PostgreSQLCanonicalLedger,PostgreSQLPackageCatalogRepository
from jmoraIs.infrastructure.scientific_citation_persistence import PostgreSQLScientificCitationRepository
from jmoraIs.vancouver import StrictVancouverFormatter
from jmoraIs.medical_documents import CanonicalDocumentCitationAdapter
from tests.test_guideline_engine import EvidenceQuery,evidence
from tests.test_evidence_package_boundary import NOW,verified_article
pytestmark=pytest.mark.integration

@pytest.fixture()
def database():
    url=os.getenv("JMORAIS_TEST_POSTGRES_URL")
    if not url:pytest.skip("JMORAIS_TEST_POSTGRES_URL is required")
    config=Config("alembic.ini");config.set_main_option("sqlalchemy.url",url);command.upgrade(config,"head")
    engine=create_engine(url,future=True);yield engine;engine.dispose()

def test_restart_reconstructs_exact_citation_and_postgresql_rejects_mutation(database):
    suffix=uuid4().hex;article=verified_article();article.article_id=f"article-{suffix}";article.authors=["Doe J"];article.journal="Journal";article.publication_year=2025
    ledger=PostgreSQLCanonicalLedger(database);claim=ledger.create_claim("citation claim",claim_id=f"claim-{suffix}",created_at=NOW)
    _,support,_=ledger.register_evidence(claim_id=claim.claim_id,source_name="NCBI",source_type="pubmed",passage="exact",
      pmid=article.pmid,doi=article.doi,payload_hash=hash_payload({"article":article.article_id}),retrieved_at=NOW,
      verification_version="ST-02",pipeline_version="ST-04",policy_version="ST-02",support_direction="supporting",occurred_at=NOW)
    packages=ScientificEvidencePackagePort(catalog=PostgreSQLPackageCatalogRepository(database),clock=lambda:NOW)
    package=packages.issue(article=article,ledger=ledger,claim_id=claim.claim_id,support_ids=(support.support_id,),pipeline_version="ST-04")
    vancouver=StrictVancouverFormatter(packages,clock=lambda:NOW).render(package_id=package.package_id,article=article)
    original=ScientificCitationService(PostgreSQLScientificCitationRepository(database),packages,clock=lambda:NOW).issue(package_id=package.package_id,article=article,vancouver_reference=vancouver)

    restarted_engine=create_engine(database.url,future=True)
    restarted_packages=ScientificEvidencePackagePort(catalog=PostgreSQLPackageCatalogRepository(restarted_engine),clock=lambda:NOW)
    recovered=ScientificCitationService(PostgreSQLScientificCitationRepository(restarted_engine),restarted_packages,clock=lambda:NOW).current_by_package(package.package_id)
    assert recovered==original and recovered.metadata.title==article.title and recovered.vancouver_reference==vancouver
    governed=replace(evidence(),evidence_package_id=package.package_id)
    projected=CanonicalDocumentCitationAdapter(EvidenceQuery((governed,)),ScientificCitationService(PostgreSQLScientificCitationRepository(restarted_engine),restarted_packages,clock=lambda:NOW)).get(governed.governed_evidence_id)
    assert projected.citation_reference_id==original.citation_record_id
    assert projected.canonical_vancouver==original.vancouver_reference.rendered_text
    assert projected.publication_identity_id==article.article_id and projected.pmid==article.pmid
    with pytest.raises(Exception,match="append-only"),database.begin() as connection:
        connection.execute(text("UPDATE scientific_citation_record_versions SET rendered_vancouver='altered' WHERE citation_record_id=:id"),{"id":original.citation_record_id})
    with pytest.raises(Exception,match="append-only"),database.begin() as connection:
        connection.execute(text("DELETE FROM scientific_citation_record_versions WHERE citation_record_id=:id"),{"id":original.citation_record_id})
    restarted_engine.dispose()
