from __future__ import annotations
from dataclasses import asdict,dataclass
from datetime import datetime
from hashlib import sha256
import json
from jmoraIs.governed_llm_draft.exact_reference import PersistedGovernedLLMDraftReference,validate_governed_draft_reference

class HumanReviewExactReferenceError(RuntimeError):pass
class HumanReviewReferenceRejected(HumanReviewExactReferenceError):pass
class LegacyMissingPersistedHumanReviewReference(HumanReviewReferenceRejected):pass

@dataclass(frozen=True)
class PersistedHumanReviewReference:
    reference_id:str;review_event_id:str;draft_reference:PersistedGovernedLLMDraftReference
    stream_position:int;tenant_id:str;reviewer_id:str;reviewer_role:str;decision:str;resulting_state:str
    policy_version:str;request_id:str;correlation_id:str;predecessor_event_id:str|None;previous_hash:str|None
    event_integrity_hash:str;integrity_hash:str;issued_at:datetime
    def __post_init__(self):
        required=(self.reference_id,self.review_event_id,self.tenant_id,self.reviewer_id,self.reviewer_role,self.decision,
            self.resulting_state,self.policy_version,self.request_id,self.correlation_id,self.event_integrity_hash,self.integrity_hash)
        if any(not isinstance(v,str) or not v.strip() for v in required):raise HumanReviewReferenceRejected("complete human review reference metadata is required")
        if self.stream_position<1:raise HumanReviewReferenceRejected("review stream position must be positive")
        if not validate_governed_draft_reference(self.draft_reference) or self.draft_reference.tenant_id!=self.tenant_id:
            raise HumanReviewReferenceRejected("typed governed draft reference is invalid")
        if any(len(v)!=64 for v in (self.event_integrity_hash,self.integrity_hash)):raise HumanReviewReferenceRejected("reference hashes must be SHA-256")
        if self.previous_hash is not None and len(self.previous_hash)!=64:raise HumanReviewReferenceRejected("previous hash is invalid")
        if self.issued_at.tzinfo is None:raise HumanReviewReferenceRejected("issued_at must be timezone-aware")
def _default(v):return v.value if hasattr(v,"value") else v.isoformat() if isinstance(v,datetime) else str(v)
def human_review_reference_integrity(reference):
    material=asdict(reference);material.pop("integrity_hash");return sha256(json.dumps(material,sort_keys=True,separators=(",",":"),default=_default).encode()).hexdigest()
def validate_human_review_reference(reference):return isinstance(reference,PersistedHumanReviewReference) and human_review_reference_integrity(reference)==reference.integrity_hash
