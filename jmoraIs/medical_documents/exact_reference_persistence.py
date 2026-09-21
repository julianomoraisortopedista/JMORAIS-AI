from __future__ import annotations
from dataclasses import replace
from datetime import datetime,timezone
from hashlib import sha256
import json
from uuid import uuid4
from sqlalchemy import text
from jmoraIs.tenancy.context import current_tenant_context
from jmoraIs.guideline_engine.domain import PersistedGuidelineRecommendationSetReference
from jmoraIs.orthopedic_intelligence.domain import PersistedOrthopedicAssessmentSetReference
from .domain import MedicalDocumentVersion
from .persistence import MedicalDocumentJsonCodec
from .exact_reference import *


class PostgreSQLMedicalDocumentExactReferenceRepository:
    def __init__(self,engine,*,clock=None,codec=None):
        if engine.dialect.name!="postgresql": raise ValueError("exact document references require PostgreSQL")
        self._engine=engine;self._clock=clock or (lambda:datetime.now(timezone.utc));self._codec=codec or MedicalDocumentJsonCodec()

    def reference_for(self,value:MedicalDocumentVersion):
        if not isinstance(value,MedicalDocumentVersion): raise MedicalDocumentReferenceRejected("typed MedicalDocumentVersion is required")
        canonical,row=self._validate_exact(value.version_id)
        if canonical!=value: raise MedicalDocumentReferenceRejected("document version does not match canonical persistence")
        tenant=current_tenant_context();document=value.document;policy=";".join(sorted(set(document.policy_versions)))
        if row["tenant_id"]!=tenant.tenant_id or not policy: raise MedicalDocumentReferenceRejected("document tenant or policy is invalid")
        self._validate_upstream_references(document)
        encoded=self._codec.encode(value);document_hash=sha256(json.dumps(encoded,sort_keys=True,separators=(",",":")).encode()).hexdigest()
        unsigned=PersistedMedicalDocumentVersionReference("mdr_"+uuid4().hex,value.document_stream_id,document.document_id,
            value.version_id,value.version,value.previous_version_id,tenant.tenant_id,policy,document.document_type.value,
            str(document.validation.valid).upper(),document.review_status.value,document_hash,provenance_reference(value),
            document.reasoning_input_id,document.reasoning_input_version,document.clinical_state_reference_id,
            document.clinical_state_version,document.guideline_recommendation_set_reference,
            document.orthopedic_assessment_set_reference,traceability_hash(value),"0"*64,self._clock())
        reference=replace(unsigned,integrity_hash=medical_document_reference_integrity(unsigned))
        with self._engine.begin() as c:c.execute(text("""INSERT INTO medical_document_persisted_references
          (reference_id,document_stream_id,document_id,version_id,document_version,predecessor,tenant_id,policy_version,
           document_type,validation_status,review_status,document_integrity_hash,provenance_reference,reasoning_input_id,
           reasoning_input_version,clinical_state_reference_id,clinical_state_version,guideline_reference_id,
           orthopedic_reference_id,traceability_hash,integrity_hash,issued_at)
          VALUES(:reference,:stream,:document,:version_id,:version,:predecessor,:tenant,:policy,:type,:validation,:review,
           :document_hash,:provenance,:reasoning,:reasoning_version,:state,:state_version,:guideline,:orthopedic,
           :traceability,:integrity,:issued)"""),{"reference":reference.reference_id,"stream":reference.document_stream_id,
          "document":reference.document_id,"version_id":reference.version_id,"version":reference.version,
          "predecessor":reference.predecessor,"tenant":reference.tenant_id,"policy":reference.policy_version,
          "type":reference.document_type,"validation":reference.validation_status,"review":reference.review_status,
          "document_hash":reference.document_integrity_hash,"provenance":reference.provenance_reference,
          "reasoning":reference.reasoning_input_id,"reasoning_version":reference.reasoning_input_version,
          "state":reference.clinical_state_reference_id,"state_version":reference.clinical_state_version,
          "guideline":reference.guideline_reference.reference_id if reference.guideline_reference else None,
          "orthopedic":reference.orthopedic_reference.reference_id if reference.orthopedic_reference else None,
          "traceability":reference.traceability_hash,"integrity":reference.integrity_hash,"issued":reference.issued_at})
        return reference

    def get_exact(self,reference):
        if not validate_medical_document_reference(reference): raise MedicalDocumentReferenceRejected("authentic owner-issued document reference is required")
        tenant=current_tenant_context()
        if tenant.tenant_id!=reference.tenant_id: raise MedicalDocumentReferenceRejected("document tenant mismatch")
        with self._engine.connect() as c:
            row=c.execute(text("SELECT * FROM medical_document_persisted_references WHERE reference_id=:id"),{"id":reference.reference_id}).mappings().first()
            guideline_row=c.execute(text("SELECT * FROM guideline_recommendation_set_references WHERE reference_id=:id"),{"id":row["guideline_reference_id"] if row else None}).mappings().first()
            orthopedic_row=c.execute(text("SELECT * FROM orthopedic_assessment_set_references WHERE reference_id=:id"),{"id":row["orthopedic_reference_id"] if row else None}).mappings().first()
        if row is None: raise LegacyNonOwnerIssuedMedicalDocumentReference("LEGACY_NON_OWNER_ISSUED_MEDICAL_DOCUMENT_REFERENCE")
        guideline=self._decode_guideline_reference(guideline_row) if guideline_row else None
        orthopedic=self._decode_orthopedic_reference(orthopedic_row) if orthopedic_row else None
        persisted=self._decode_reference(row,guideline,orthopedic)
        if persisted!=reference: raise MedicalDocumentReferenceRejected("persisted document reference is inconsistent")
        value,_=self._validate_exact(reference.version_id)
        if self._linkage(value,reference)!=self._reference_linkage(reference): raise MedicalDocumentReferenceRejected("document exact linkage mismatch")
        return value

    def _validate_exact(self,version_id):
        with self._engine.connect() as c:
            row=c.execute(text("SELECT * FROM medical_document_versions WHERE version_id=:id"),{"id":version_id}).mappings().first()
            if row is None: raise LegacyNonOwnerIssuedMedicalDocumentReference("LEGACY_NON_OWNER_ISSUED_MEDICAL_DOCUMENT_REFERENCE")
            chain=c.execute(text("SELECT version_id,version,previous_version_id FROM medical_document_versions WHERE document_stream_id=:s AND version<=:v ORDER BY version"),{"s":row["document_stream_id"],"v":row["version"]}).mappings().all()
        value=self._codec.decode(row["payload"])
        expected=(value.version_id,value.document_stream_id,value.version,value.previous_version_id,value.document.document_id,
            value.document.document_type.value,value.document.status.value,value.document.review_status.value,value.document.template_version,value.created_at)
        actual=tuple(row[k] for k in ("version_id","document_stream_id","version","previous_version_id","document_id","document_type","status","review_status","template_version","created_at"))
        if expected!=actual or len(chain)!=value.version: raise MedicalDocumentReferenceRejected("document persistence or version chain is invalid")
        for i,item in enumerate(chain,1):
            previous=chain[i-2]["version_id"] if i>1 else None
            if item["version"]!=i or item["previous_version_id"]!=previous: raise MedicalDocumentReferenceRejected("document predecessor continuity is invalid")
        return value,row

    def _validate_upstream_references(self,document):
        guideline=document.guideline_recommendation_set_reference;orthopedic=document.orthopedic_assessment_set_reference
        with self._engine.connect() as c:
            guideline_row=c.execute(text("SELECT * FROM guideline_recommendation_set_references WHERE reference_id=:id"),{"id":guideline.reference_id if guideline else None}).mappings().first()
            orthopedic_row=c.execute(text("SELECT * FROM orthopedic_assessment_set_references WHERE reference_id=:id"),{"id":orthopedic.reference_id if orthopedic else None}).mappings().first()
        if guideline is not None and (guideline_row is None or self._decode_guideline_reference(guideline_row)!=guideline):
            raise MedicalDocumentReferenceRejected("exact guideline reference linkage is invalid")
        if orthopedic is not None and (orthopedic_row is None or self._decode_orthopedic_reference(orthopedic_row)!=orthopedic):
            raise MedicalDocumentReferenceRejected("exact orthopedic reference linkage is invalid")

    def _linkage(self,v,r):
        d=v.document;encoded=self._codec.encode(v);digest=sha256(json.dumps(encoded,sort_keys=True,separators=(",",":")).encode()).hexdigest()
        return (v.document_stream_id,d.document_id,v.version_id,v.version,v.previous_version_id,";".join(sorted(set(d.policy_versions))),
            d.document_type.value,str(d.validation.valid).upper(),d.review_status.value,digest,provenance_reference(v),d.reasoning_input_id,
            d.reasoning_input_version,d.clinical_state_reference_id,d.clinical_state_version,d.guideline_recommendation_set_reference,
            d.orthopedic_assessment_set_reference,traceability_hash(v))
    @staticmethod
    def _reference_linkage(r): return (r.document_stream_id,r.document_id,r.version_id,r.version,r.predecessor,r.policy_version,r.document_type,r.validation_status,r.review_status,r.document_integrity_hash,r.provenance_reference,r.reasoning_input_id,r.reasoning_input_version,r.clinical_state_reference_id,r.clinical_state_version,r.guideline_reference,r.orthopedic_reference,r.traceability_hash)
    @staticmethod
    def _decode_reference(row,guideline=None,orthopedic=None):
        return PersistedMedicalDocumentVersionReference(row["reference_id"],row["document_stream_id"],row["document_id"],row["version_id"],row["document_version"],row["predecessor"],row["tenant_id"],row["policy_version"],row["document_type"],row["validation_status"],row["review_status"],row["document_integrity_hash"],row["provenance_reference"],row["reasoning_input_id"],row["reasoning_input_version"],row["clinical_state_reference_id"],row["clinical_state_version"],guideline,orthopedic,row["traceability_hash"],row["integrity_hash"],row["issued_at"])
    @staticmethod
    def _decode_guideline_reference(row):
        return PersistedGuidelineRecommendationSetReference(row["reference_id"],row["set_id"],row["set_version"],row["subject_reference"],row["tenant_id"],row["policy_version"],row["integrity_hash"],row["issued_at"])
    @staticmethod
    def _decode_orthopedic_reference(row):
        return PersistedOrthopedicAssessmentSetReference(row["reference_id"],row["set_id"],row["set_version"],row["subject_reference"],row["tenant_id"],row["policy_version"],row["integrity_hash"],row["issued_at"])
