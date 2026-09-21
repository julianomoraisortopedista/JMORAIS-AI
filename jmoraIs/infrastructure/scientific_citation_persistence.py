from __future__ import annotations
from datetime import date,datetime
from sqlalchemy import BigInteger,DateTime,ForeignKey,Integer,JSON,String,Text,UniqueConstraint,select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped,mapped_column,sessionmaker
from jmoraIs.application.scientific_citations import ReconciledBibliographicMetadata,ScientificCitationConflict,ScientificCitationRecord
from jmoraIs.infrastructure.postgresql_package_catalog import PackageCatalogBase
from jmoraIs.vancouver import VancouverReference

class InMemoryScientificCitationRepository:
    def __init__(self):self._records=[]
    def append(self,record):
        history=self.history(record.evidence_package_id);expected=len(history)+1;previous=history[-1].citation_record_id if history else None
        if record.version!=expected or record.predecessor_record_id!=previous or any(x.citation_record_id==record.citation_record_id for x in self._records):raise ScientificCitationConflict("citation predecessor/version is invalid")
        self._records.append(record)
    def get(self,citation_record_id):return next((x for x in self._records if x.citation_record_id==citation_record_id),None)
    def current_by_package(self,package_id):
        history=self.history(package_id);return history[-1] if history else None
    def history(self,package_id):return tuple(x for x in self._records if x.evidence_package_id==package_id)

class ScientificCitationRecordRow(PackageCatalogBase):
    __tablename__="scientific_citation_record_versions"
    __table_args__=(UniqueConstraint("evidence_package_id","version",name="uq_scientific_citation_package_version"),)
    sequence_id:Mapped[int]=mapped_column(BigInteger,primary_key=True,autoincrement=True)
    citation_record_id:Mapped[str]=mapped_column(String(64),unique=True,nullable=False)
    evidence_package_id:Mapped[str]=mapped_column(ForeignKey("evidence_package_catalog.package_id",ondelete="RESTRICT"),nullable=False,index=True)
    publication_identity_id:Mapped[str]=mapped_column(String(64),nullable=False)
    version:Mapped[int]=mapped_column(Integer,nullable=False);predecessor_record_id:Mapped[str|None]=mapped_column(ForeignKey("scientific_citation_record_versions.citation_record_id",ondelete="RESTRICT"))
    publication_status:Mapped[str]=mapped_column(String(40),nullable=False);policy_version:Mapped[str]=mapped_column(String(64),nullable=False)
    formatter_version:Mapped[str]=mapped_column(String(64),nullable=False);rendered_vancouver:Mapped[str]=mapped_column(Text,nullable=False)
    metadata_payload:Mapped[dict]=mapped_column(JSON,nullable=False);linkage_payload:Mapped[dict]=mapped_column(JSON,nullable=False)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False);integrity_hash:Mapped[str]=mapped_column(String(64),nullable=False)

class PostgreSQLScientificCitationRepository:
    def __init__(self,engine):self._sessions=sessionmaker(bind=engine,expire_on_commit=False)
    def append(self,record):
        history=self.history(record.evidence_package_id);expected=len(history)+1;previous=history[-1].citation_record_id if history else None
        if record.version!=expected or record.predecessor_record_id!=previous:raise ScientificCitationConflict("citation predecessor/version is invalid")
        with self._sessions.begin() as session:
            session.add(_row(record))
            try:session.flush()
            except IntegrityError as exc:raise ScientificCitationConflict("citation history is append-only") from exc
    def get(self,citation_record_id):
        with self._sessions() as session:row=session.scalar(select(ScientificCitationRecordRow).where(ScientificCitationRecordRow.citation_record_id==citation_record_id))
        return _record(row) if row else None
    def current_by_package(self,package_id):
        with self._sessions() as session:row=session.scalar(select(ScientificCitationRecordRow).where(ScientificCitationRecordRow.evidence_package_id==package_id).order_by(ScientificCitationRecordRow.version.desc()).limit(1))
        return _record(row) if row else None
    def history(self,package_id):
        with self._sessions() as session:rows=session.scalars(select(ScientificCitationRecordRow).where(ScientificCitationRecordRow.evidence_package_id==package_id).order_by(ScientificCitationRecordRow.version)).all()
        return tuple(_record(row) for row in rows)

def _metadata(value):
    data=dict(value.__dict__);data["authors"]=list(value.authors);data["editors"]=list(value.editors);data["accessed_at"]=value.accessed_at.isoformat() if value.accessed_at else None;return data
def _row(value):
    v=value.vancouver_reference
    return ScientificCitationRecordRow(citation_record_id=value.citation_record_id,evidence_package_id=value.evidence_package_id,
      publication_identity_id=value.publication_identity_id,version=value.version,predecessor_record_id=value.predecessor_record_id,
      publication_status=value.publication_status,policy_version=value.policy_version,formatter_version=v.formatter_version,
      rendered_vancouver=v.rendered_text,metadata_payload=_metadata(value.metadata),linkage_payload={"vancouver_citation_id":v.citation_id,
      "vancouver_created_at":v.created_at.isoformat(),"metadata_hash":value.metadata_hash,"provenance_references":list(value.provenance_references),
      "verification_references":list(value.verification_references),"ledger_references":list(value.ledger_references),"publication_type":v.publication_type},
      created_at=value.created_at,integrity_hash=value.integrity_hash)
def _record(row):
    metadata=dict(row.metadata_payload);metadata["authors"]=tuple(metadata["authors"]);metadata["editors"]=tuple(metadata["editors"]);metadata["accessed_at"]=date.fromisoformat(metadata["accessed_at"]) if metadata.get("accessed_at") else None
    link=row.linkage_payload;v=VancouverReference(link["vancouver_citation_id"],row.evidence_package_id,link["publication_type"],row.formatter_version,row.rendered_vancouver,datetime.fromisoformat(link["vancouver_created_at"]))
    return ScientificCitationRecord(row.citation_record_id,row.evidence_package_id,row.publication_identity_id,ReconciledBibliographicMetadata(**metadata),v,link["metadata_hash"],tuple(link["provenance_references"]),tuple(link["verification_references"]),tuple(link["ledger_references"]),row.policy_version,row.publication_status,row.created_at,row.version,row.predecessor_record_id,row.integrity_hash)
