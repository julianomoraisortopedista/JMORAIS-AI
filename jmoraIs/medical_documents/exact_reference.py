from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from hashlib import sha256
import json

from jmoraIs.guideline_engine.domain import PersistedGuidelineRecommendationSetReference
from jmoraIs.orthopedic_intelligence.domain import PersistedOrthopedicAssessmentSetReference


class MedicalDocumentExactReferenceError(RuntimeError): pass
class MedicalDocumentReferenceRejected(MedicalDocumentExactReferenceError): pass
class LegacyNonOwnerIssuedMedicalDocumentReference(MedicalDocumentReferenceRejected): pass


@dataclass(frozen=True)
class PersistedMedicalDocumentVersionReference:
    reference_id: str
    document_stream_id: str
    document_id: str
    version_id: str
    version: int
    predecessor: str | None
    tenant_id: str
    policy_version: str
    document_type: str
    validation_status: str
    review_status: str
    document_integrity_hash: str
    provenance_reference: str
    reasoning_input_id: str
    reasoning_input_version: int
    clinical_state_reference_id: str
    clinical_state_version: int
    guideline_reference: PersistedGuidelineRecommendationSetReference | None
    orthopedic_reference: PersistedOrthopedicAssessmentSetReference | None
    traceability_hash: str
    integrity_hash: str
    issued_at: datetime

    def __post_init__(self):
        required=(self.reference_id,self.document_stream_id,self.document_id,self.version_id,self.tenant_id,
            self.policy_version,self.document_type,self.validation_status,self.review_status,
            self.document_integrity_hash,self.provenance_reference,self.reasoning_input_id,
            self.clinical_state_reference_id,self.traceability_hash,self.integrity_hash)
        if any(not isinstance(v,str) or not v.strip() for v in required):
            raise MedicalDocumentReferenceRejected("complete document reference metadata is required")
        if min(self.version,self.reasoning_input_version,self.clinical_state_version)<1:
            raise MedicalDocumentReferenceRejected("document linkage versions must be positive")
        if any(len(v)!=64 for v in (self.document_integrity_hash,self.traceability_hash,self.integrity_hash)):
            raise MedicalDocumentReferenceRejected("document reference hashes must be SHA-256")
        if self.issued_at.tzinfo is None: raise MedicalDocumentReferenceRejected("issued_at must be timezone-aware")


def _default(v): return v.value if hasattr(v,"value") else v.isoformat() if isinstance(v,datetime) else str(v)
def _hash(v): return sha256(json.dumps(v,sort_keys=True,separators=(",",":"),default=_default).encode()).hexdigest()
def medical_document_reference_integrity(reference):
    material=asdict(reference);material.pop("integrity_hash");return _hash(material)
def validate_medical_document_reference(reference):
    return isinstance(reference,PersistedMedicalDocumentVersionReference) and medical_document_reference_integrity(reference)==reference.integrity_hash
def provenance_reference(version): return "medical-document-provenance:"+_hash(list(version.document.provenance_references))
def traceability_hash(version): return _hash(asdict(version.document.traceability))
