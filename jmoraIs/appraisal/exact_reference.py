from __future__ import annotations
from dataclasses import asdict,dataclass
from datetime import datetime
from hashlib import sha256
import json

class GovernedEvidenceExactReferenceError(RuntimeError):pass
class GovernedEvidenceReferenceRejected(GovernedEvidenceExactReferenceError):pass
class LegacyMissingPersistedGovernedEvidenceReference(GovernedEvidenceExactReferenceError):pass

@dataclass(frozen=True)
class PersistedGovernedEvidenceReference:
    reference_id:str;governed_evidence_id:str;stream_version:int;tenant_id:str
    evidence_package_id:str;appraisal_record_id:str;appraisal_record_version:int
    policy_version:str;lifecycle_event_id:str;lifecycle_status:str
    lifecycle_integrity_hash:str;provenance_reference:str
    governed_evidence_integrity_hash:str;integrity_hash:str;issued_at:datetime
    def __post_init__(self):
        values=(self.reference_id,self.governed_evidence_id,self.tenant_id,self.evidence_package_id,
            self.appraisal_record_id,self.policy_version,self.lifecycle_event_id,self.lifecycle_status,
            self.lifecycle_integrity_hash,self.provenance_reference,
            self.governed_evidence_integrity_hash,self.integrity_hash)
        if any(not isinstance(value,str) or not value.strip() for value in values):raise GovernedEvidenceReferenceRejected("complete GovernedEvidence reference metadata is required")
        if self.stream_version<1 or self.appraisal_record_version<1:raise GovernedEvidenceReferenceRejected("canonical versions must be positive")
        if self.lifecycle_status!="ACTIVE":raise GovernedEvidenceReferenceRejected("only ACTIVE GovernedEvidence can be referenced")
        if any(len(value)!=64 for value in (self.lifecycle_integrity_hash,self.governed_evidence_integrity_hash,self.integrity_hash)):raise GovernedEvidenceReferenceRejected("reference hashes must be SHA-256")
        if self.issued_at.tzinfo is None:raise GovernedEvidenceReferenceRejected("reference timestamp must be timezone-aware")

def _hash(value):return sha256(json.dumps(value,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def provenance_reference(evidence):return "governed-evidence-provenance:"+_hash(list(evidence.provenance_references))
def reference_integrity(reference):
    value=asdict(reference);value.pop("integrity_hash");value["issued_at"]=reference.issued_at.isoformat();return _hash(value)
def validate_reference_integrity(reference):return isinstance(reference,PersistedGovernedEvidenceReference) and reference_integrity(reference)==reference.integrity_hash
