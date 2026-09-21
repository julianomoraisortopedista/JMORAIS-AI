from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional
from jmoraIs.gateway_input import UpstreamArtifactReference
from jmoraIs.clinical.governed import HumanReviewStatus
from jmoraIs.clinical.review_governance import ReviewerRole

class LLMHumanReviewError(RuntimeError):pass
class LLMHumanReviewRejected(LLMHumanReviewError):pass
class LLMReviewDecision(str,Enum):APPROVE="APPROVE";REJECT="REJECT";REQUEST_CLARIFICATION="REQUEST_CLARIFICATION"
class LLMHumanReviewSecurityEventType(str,Enum):
    REVIEW_ATTEMPT="REVIEW_ATTEMPT";REVIEW_AUTHORIZED="REVIEW_AUTHORIZED";REVIEW_AUTHORIZATION_DENIED="REVIEW_AUTHORIZATION_DENIED"
    SESSION_REJECTED="SESSION_REJECTED";IDENTITY_REJECTED="IDENTITY_REJECTED";REVIEWER_REJECTED="REVIEWER_REJECTED"
    TENANT_MISMATCH="TENANT_MISMATCH";PURPOSE_REJECTED="PURPOSE_REJECTED";DRAFT_INTEGRITY_REJECTED="DRAFT_INTEGRITY_REJECTED"
    DRAFT_LIFECYCLE_REJECTED="DRAFT_LIFECYCLE_REJECTED";INVALID_TRANSITION="INVALID_TRANSITION"
    REVIEW_APPROVED="REVIEW_APPROVED";REVIEW_REJECTED="REVIEW_REJECTED";REVIEW_CLARIFICATION_REQUESTED="REVIEW_CLARIFICATION_REQUESTED"
@dataclass(frozen=True)
class LLMHumanReviewEvent:
    review_event_id:str;draft_id:str;draft_version:int;invocation_id:str;request_id:str;correlation_id:str;tenant_id:str
    upstream_artifact_reference:UpstreamArtifactReference;prior_state:HumanReviewStatus;resulting_state:HumanReviewStatus;decision:LLMReviewDecision
    reviewer_id:str;reviewer_role:ReviewerRole;organization_id:str;policy_version:str;justification_reference:str;occurred_at:datetime
    stream_position:int;predecessor_event_id:Optional[str];previous_hash:Optional[str];integrity_hash:str
@dataclass(frozen=True)
class LLMHumanReviewState:
    draft_id:str;draft_version:int;status:HumanReviewStatus;latest_event_id:Optional[str];externally_actionable:bool=False
@dataclass(frozen=True)
class UpstreamReviewConstraints:
    critical_conflicts:tuple[str,...];generated_by:Optional[str]=None
@dataclass(frozen=True)
class LLMHumanReviewSecurityEvent:
    event_id:str;event_type:LLMHumanReviewSecurityEventType;draft_id:Optional[str];draft_version:Optional[int]
    invocation_id:Optional[str];request_id:Optional[str];correlation_id:str;tenant_id:Optional[str];principal_id:Optional[str]
    reviewer_id:Optional[str];reviewer_role:Optional[str];organization_id:Optional[str];result:str;reason_code:str
    policy_version:str;occurred_at:datetime;stream_position:int;previous_hash:Optional[str];integrity_hash:str
