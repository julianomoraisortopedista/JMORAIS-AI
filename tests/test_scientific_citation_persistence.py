from dataclasses import replace
from datetime import datetime,timezone
import pytest
from jmoraIs.application.evidence_packages import ScientificEvidencePackagePort
from jmoraIs.application.scientific_citations import ScientificCitationIntegrityError,ScientificCitationRejected,ScientificCitationService,citation_integrity_payload
from jmoraIs.evidence_ledger import AppendOnlyEvidenceLedger,LedgerEventType,hash_payload
from jmoraIs.infrastructure.package_catalog import InMemoryPackageCatalogRepository
from jmoraIs.infrastructure.scientific_citation_persistence import InMemoryScientificCitationRepository
from jmoraIs.scientific_domain import ExistenceVerificationStatus,IdentifierVerificationResult,MetadataReconciliationStatus,PublicationStatus,PublicationVerificationRecord,ScientificArticle,SourceProvenance
from jmoraIs.vancouver import StrictVancouverFormatter,VancouverReference
NOW=datetime(2026,1,1,tzinfo=timezone.utc)

def setup(status=PublicationStatus.RELIABLE.value):
    article=ScientificArticle(article_id="article-1",title="Verified study",authors=["Doe J"],journal="Journal",publication_year=2025,pmid="12345678",publication_type="journal_article",publication_status=status,verification_status="VERIFIED",provenance=SourceProvenance(source_id="prov-1",source_name="NCBI"),verification_record=PublicationVerificationRecord(identifier_results=(IdentifierVerificationResult("PMID","12345678",True,ExistenceVerificationStatus.CONFIRMED.value,"NCBI",checked_at=NOW),),reconciliation_status=MetadataReconciliationStatus.MATCHED.value,final_status="VERIFIED",policy_version="ST-02",search_run_id="search-1"))
    ledger=AppendOnlyEvidenceLedger();claim=ledger.create_claim("claim",claim_id="claim-1",created_at=NOW)
    _,support,_=ledger.register_evidence(claim_id=claim.claim_id,source_name="NCBI",source_type="pubmed",passage="exact",pmid=article.pmid,payload_hash=hash_payload({"article":"article-1"}),retrieved_at=NOW,verification_version="ST-02",pipeline_version="ST-03",policy_version="ST-02",support_direction="supporting",occurred_at=NOW)
    packages=ScientificEvidencePackagePort(catalog=InMemoryPackageCatalogRepository(),clock=lambda:NOW)
    package=packages.issue(article=article,ledger=ledger,claim_id=claim.claim_id,support_ids=(support.support_id,),pipeline_version="ST-04")
    vancouver=StrictVancouverFormatter(packages,clock=lambda:NOW).render(package_id=package.package_id,article=article)
    repository=InMemoryScientificCitationRepository();service=ScientificCitationService(repository,packages,clock=lambda:NOW)
    return article,ledger,support,packages,package,vancouver,repository,service

def test_issue_query_and_versioned_formatter_history():
    article,_,_,_,package,vancouver,_,service=setup();first=service.issue(package_id=package.package_id,article=article,vancouver_reference=vancouver)
    second=service.issue(package_id=package.package_id,article=article,vancouver_reference=replace(vancouver,citation_id="citation-v2",formatter_version="vancouver-future-2"))
    assert service.current_by_package(package.package_id)==second
    assert second.predecessor_record_id==first.citation_record_id and second.version==2
    assert service.history(package.package_id)==(first,second)

def test_corrected_status_is_explicit():
    article,*rest=setup(PublicationStatus.CORRECTED.value);package=rest[3];vancouver=rest[4];service=rest[6]
    assert service.issue(package_id=package.package_id,article=article,vancouver_reference=vancouver).publication_status=="CORRECTED"

def test_retracted_publication_is_blocked():
    article,*rest=setup(PublicationStatus.RETRACTED.value);package=rest[3];vancouver=rest[4];service=rest[6]
    with pytest.raises(ScientificCitationRejected,match="retracted"):service.issue(package_id=package.package_id,article=article,vancouver_reference=vancouver)

def test_missing_package_provenance_and_broken_links_fail_closed():
    article,_,_,_,package,vancouver,repo,service=setup()
    with pytest.raises(ScientificCitationRejected):service.issue(package_id="missing",article=article,vancouver_reference=vancouver)
    record=service.issue(package_id=package.package_id,article=article,vancouver_reference=vancouver)
    repo._records[0]=replace(record,provenance_references=())
    with pytest.raises(ScientificCitationIntegrityError):service.get(record.citation_record_id)

@pytest.mark.parametrize("field,value",[("integrity_hash","bad"),("metadata_hash","bad"),("ledger_references",("bad",)),("verification_references",("bad",))])
def test_tampered_citation_fields_are_rejected(field,value):
    article,_,_,_,package,vancouver,repo,service=setup();record=service.issue(package_id=package.package_id,article=article,vancouver_reference=vancouver);repo._records[0]=replace(record,**{field:value})
    with pytest.raises(ScientificCitationIntegrityError):service.get(record.citation_record_id)

def test_altered_vancouver_and_metadata_are_rejected():
    article,_,_,_,package,vancouver,repo,service=setup();record=service.issue(package_id=package.package_id,article=article,vancouver_reference=vancouver)
    repo._records[0]=replace(record,vancouver_reference=replace(vancouver,rendered_text="Fabricated citation"))
    with pytest.raises(ScientificCitationIntegrityError):service.get(record.citation_record_id)
    altered=replace(record,metadata=replace(record.metadata,title="Altered"),integrity_hash="")
    altered=replace(altered,integrity_hash=hash_payload(citation_integrity_payload(altered)));repo._records[0]=altered
    with pytest.raises(ScientificCitationIntegrityError):service.get(record.citation_record_id)

@pytest.mark.parametrize("event",[LedgerEventType.RETRACTION,LedgerEventType.INVALIDATION])
def test_revoked_package_is_blocked_on_current_query(event):
    article,ledger,support,_,package,vancouver,_,service=setup();service.issue(package_id=package.package_id,article=article,vancouver_reference=vancouver)
    ledger.append_lifecycle_event(claim_id="claim-1",event_type=event,target_support_id=support.support_id,occurred_at=NOW)
    with pytest.raises(ScientificCitationRejected):service.current_by_package(package.package_id)

def test_architecture_has_no_document_or_connector_dependency():
    from pathlib import Path
    root=Path(__file__).parents[1];source=(root/"jmoraIs/application/scientific_citations.py").read_text()+(root/"jmoraIs/infrastructure/scientific_citation_persistence.py").read_text()
    assert "medical_documents" not in source and "connect.pubmed" not in source and "connect.crossref" not in source
    assert "StrictVancouverFormatter" not in source
