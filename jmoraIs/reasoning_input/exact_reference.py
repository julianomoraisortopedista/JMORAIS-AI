from __future__ import annotations
from dataclasses import asdict,dataclass
from datetime import datetime
from hashlib import sha256
import json
from jmoraIs.clinical_state.exact_reference import PersistedClinicalStateReference
from jmoraIs.appraisal.exact_reference import PersistedGovernedEvidenceReference
from jmoraIs.terminology.domain import PersistedTerminologyMappingGovernanceReference

class ClinicalReasoningInputExactReferenceError(RuntimeError):pass
class ClinicalReasoningInputReferenceRejected(ClinicalReasoningInputExactReferenceError):pass
class LegacyMissingPersistedClinicalReasoningInputReference(ClinicalReasoningInputExactReferenceError):pass

@dataclass(frozen=True)
class PersistedClinicalReasoningInputReference:
    reference_id:str;input_id:str;input_version:int;previous_input_id:str|None
    predecessor_reference_id:str|None;subject_reference:str;tenant_id:str;policy_version:str
    provenance_reference:str;input_integrity_hash:str
    clinical_state_reference:PersistedClinicalStateReference
    governed_evidence_references:tuple[PersistedGovernedEvidenceReference,...]
    terminology_governance_references:tuple[PersistedTerminologyMappingGovernanceReference,...]
    integrity_hash:str;issued_at:datetime
    def __post_init__(self):
        required=(self.reference_id,self.input_id,self.subject_reference,self.tenant_id,self.policy_version,
            self.provenance_reference,self.input_integrity_hash,self.integrity_hash)
        if any(not isinstance(x,str) or not x.strip() for x in required):raise ClinicalReasoningInputReferenceRejected("complete exact reference metadata is required")
        if self.input_version<1 or any(len(x)!=64 for x in (self.input_integrity_hash,self.integrity_hash)):raise ClinicalReasoningInputReferenceRejected("reference version or hashes are invalid")
        if self.input_version==1 and (self.previous_input_id is not None or self.predecessor_reference_id is not None):raise ClinicalReasoningInputReferenceRejected("genesis reference cannot have predecessor")
        if self.input_version>1 and (not self.previous_input_id or not self.predecessor_reference_id):raise ClinicalReasoningInputReferenceRejected("exact predecessor reference is required")
        if not self.governed_evidence_references or not self.terminology_governance_references:raise ClinicalReasoningInputReferenceRejected("complete upstream exact references are required")
        if self.issued_at.tzinfo is None:raise ClinicalReasoningInputReferenceRejected("issued_at must be timezone-aware")

def _json(value):
    if isinstance(value,datetime):return value.isoformat()
    if hasattr(value,"value"):return value.value
    raise TypeError
def _hash(value):return sha256(json.dumps(value,sort_keys=True,separators=(",",":"),default=_json).encode()).hexdigest()
def reference_integrity(reference):
    value=asdict(reference);value.pop("integrity_hash");return _hash(value)
def input_integrity(codec,value):return _hash(codec.encode(value))
def provenance_reference(value):return "reasoning-input-provenance:"+_hash([asdict(item) for item in value.provenance_references])
def validate_reference_integrity(value):return isinstance(value,PersistedClinicalReasoningInputReference) and reference_integrity(value)==value.integrity_hash
