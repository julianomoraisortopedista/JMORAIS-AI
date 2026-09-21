from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Optional, Protocol
from uuid import uuid4

from jmoraIs.application.evidence_packages import EvidencePackageError, ScientificEvidencePackagePort, publication_metadata_hash
from jmoraIs.evidence_ledger import hash_payload
from jmoraIs.scientific_domain import PublicationStatus, ScientificArticle, VerificationStatus, utc_now
from jmoraIs.vancouver import VancouverReference

class ScientificCitationError(RuntimeError): pass
class ScientificCitationRejected(ScientificCitationError): pass
class ScientificCitationConflict(ScientificCitationError): pass
class ScientificCitationIntegrityError(ScientificCitationError): pass

@dataclass(frozen=True)
class ReconciledBibliographicMetadata:
    article_id:str; title:str; authors:tuple[str,...]; journal:Optional[str]; journal_abbreviation:Optional[str]
    publication_year:Optional[int]; volume:Optional[str]; issue:Optional[str]; pages:Optional[str]
    publication_type:Optional[str]; publisher:Optional[str]; publication_place:Optional[str]
    book_title:Optional[str]; chapter_title:Optional[str]; editors:tuple[str,...]; url:Optional[str]
    accessed_at:Optional[date]; pmid:Optional[str]; doi:Optional[str]; pmcid:Optional[str]

@dataclass(frozen=True)
class ScientificCitationRecord:
    citation_record_id:str; evidence_package_id:str; publication_identity_id:str
    metadata:ReconciledBibliographicMetadata; vancouver_reference:VancouverReference; metadata_hash:str
    provenance_references:tuple[str,...]; verification_references:tuple[str,...]; ledger_references:tuple[str,...]
    policy_version:str; publication_status:str; created_at:datetime; version:int
    predecessor_record_id:Optional[str]; integrity_hash:str

class ScientificCitationRepository(Protocol):
    def append(self,record:ScientificCitationRecord)->None:...
    def get(self,citation_record_id:str)->Optional[ScientificCitationRecord]:...
    def current_by_package(self,package_id:str)->Optional[ScientificCitationRecord]:...
    def history(self,package_id:str)->tuple[ScientificCitationRecord,...]:...

class ScientificCitationQueryPort(Protocol):
    def get(self,citation_record_id:str)->ScientificCitationRecord:...
    def current_by_package(self,package_id:str)->ScientificCitationRecord:...
    def history(self,package_id:str)->tuple[ScientificCitationRecord,...]:...

def bibliographic_metadata(article:ScientificArticle)->ReconciledBibliographicMetadata:
    return ReconciledBibliographicMetadata(article.article_id,article.title,tuple(article.authors),article.journal,
        article.journal_abbreviation,article.publication_year,article.volume,article.issue,article.pages,
        article.publication_type,article.publisher,article.publication_place,article.book_title,article.chapter_title,
        tuple(article.editors),article.url,article.accessed_at,article.pmid,article.doi,article.pmcid)

def citation_integrity_payload(record:ScientificCitationRecord)->dict[str,object]:
    metadata=asdict(record.metadata);metadata["authors"]=list(record.metadata.authors);metadata["editors"]=list(record.metadata.editors)
    metadata["accessed_at"]=record.metadata.accessed_at.isoformat() if record.metadata.accessed_at else None
    vancouver=asdict(record.vancouver_reference);vancouver["created_at"]=record.vancouver_reference.created_at.isoformat()
    return {"citation_record_id":record.citation_record_id,"evidence_package_id":record.evidence_package_id,
      "publication_identity_id":record.publication_identity_id,"metadata":metadata,"vancouver_reference":vancouver,
      "metadata_hash":record.metadata_hash,"provenance_references":list(record.provenance_references),
      "verification_references":list(record.verification_references),"ledger_references":list(record.ledger_references),
      "policy_version":record.policy_version,"publication_status":record.publication_status,
      "created_at":record.created_at.isoformat(),"version":record.version,"predecessor_record_id":record.predecessor_record_id}

class ScientificCitationService(ScientificCitationQueryPort):
    def __init__(self,repository:ScientificCitationRepository,packages:ScientificEvidencePackagePort,*,clock=utc_now):
        self._repository=repository;self._packages=packages;self._clock=clock
    def issue(self,*,package_id:str,article:ScientificArticle,vancouver_reference:VancouverReference)->ScientificCitationRecord:
        package=self._valid_package(package_id)
        if not isinstance(article,ScientificArticle) or not article.provenance:raise ScientificCitationRejected("canonical article provenance is required")
        if article.verification_status!=VerificationStatus.VERIFIED.value:raise ScientificCitationRejected("only VERIFIED articles may issue canonical citations")
        if article.publication_status==PublicationStatus.RETRACTED.value:raise ScientificCitationRejected("retracted publication is blocked")
        identity=next((x for x in package.publication_identities if x.article_id==article.article_id),None)
        if identity is None or identity.metadata_hash!=publication_metadata_hash(article):raise ScientificCitationRejected("article metadata is not bound to the EvidencePackage")
        if vancouver_reference.package_id!=package.package_id or not vancouver_reference.rendered_text:raise ScientificCitationRejected("Vancouver reference is not bound to the EvidencePackage")
        if not package.provenance_references or not package.verification_references or not package.ledger_references:raise ScientificCitationRejected("package trust linkage is incomplete")
        history=self._repository.history(package_id);version=len(history)+1;predecessor=history[-1].citation_record_id if history else None
        unsigned=ScientificCitationRecord(uuid4().hex,package.package_id,identity.article_id,bibliographic_metadata(article),vancouver_reference,
          identity.metadata_hash,tuple(package.provenance_references),tuple(package.verification_references),tuple(package.ledger_references),
          package.policy_version,article.publication_status,self._clock(),version,predecessor,"")
        record=ScientificCitationRecord(**{**unsigned.__dict__,"integrity_hash":hash_payload(citation_integrity_payload(unsigned))})
        self._repository.append(record);return record
    def get(self,citation_record_id):
        record=self._repository.get(citation_record_id)
        if record is None:raise ScientificCitationRejected("canonical citation does not exist")
        return self._validate(record)
    def current_by_package(self,package_id):
        record=self._repository.current_by_package(package_id)
        if record is None:raise ScientificCitationRejected("canonical citation does not exist")
        return self._validate(record)
    def history(self,package_id):
        records=self._repository.history(package_id)
        for index,record in enumerate(records):
            if record.version!=index+1 or record.predecessor_record_id!=(records[index-1].citation_record_id if index else None):raise ScientificCitationIntegrityError("citation version chain is invalid")
            self._validate(record)
        return records
    def _valid_package(self,package_id):
        try:return self._packages.get(package_id)
        except EvidencePackageError as exc:raise ScientificCitationRejected("EvidencePackage is not currently valid") from exc
    def _validate(self,record):
        package=self._valid_package(record.evidence_package_id)
        blank=ScientificCitationRecord(**{**record.__dict__,"integrity_hash":""})
        if record.integrity_hash!=hash_payload(citation_integrity_payload(blank)):raise ScientificCitationIntegrityError("canonical citation integrity check failed")
        metadata=record.metadata
        reconstructed=ScientificArticle(article_id=metadata.article_id,title=metadata.title,authors=list(metadata.authors),journal=metadata.journal,
          journal_abbreviation=metadata.journal_abbreviation,publication_year=metadata.publication_year,volume=metadata.volume,issue=metadata.issue,
          pages=metadata.pages,publication_type=metadata.publication_type,publisher=metadata.publisher,publication_place=metadata.publication_place,
          book_title=metadata.book_title,chapter_title=metadata.chapter_title,editors=list(metadata.editors),url=metadata.url,
          accessed_at=metadata.accessed_at,pmid=metadata.pmid,doi=metadata.doi,pmcid=metadata.pmcid)
        if publication_metadata_hash(reconstructed)!=record.metadata_hash:raise ScientificCitationIntegrityError("persisted bibliographic metadata hash is invalid")
        identity=next((x for x in package.publication_identities if x.article_id==record.publication_identity_id),None)
        if identity is None or identity.metadata_hash!=record.metadata_hash:raise ScientificCitationIntegrityError("publication identity linkage is invalid")
        if (record.provenance_references!=package.provenance_references or record.verification_references!=package.verification_references or
            record.ledger_references!=package.ledger_references or record.vancouver_reference.package_id!=package.package_id):raise ScientificCitationIntegrityError("package trust linkage is invalid")
        if record.publication_status==PublicationStatus.RETRACTED.value:raise ScientificCitationRejected("retracted publication is blocked")
        return record
