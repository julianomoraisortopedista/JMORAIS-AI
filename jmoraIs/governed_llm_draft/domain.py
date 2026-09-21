from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional
from jmoraIs.gateway_input import UpstreamArtifactReference

class GovernedLLMDraftError(RuntimeError): pass
class DraftBoundaryRejected(GovernedLLMDraftError): pass
class DraftVersionConflict(GovernedLLMDraftError): pass
class DraftReviewStatus(str,Enum): PENDING_REVIEW="PENDING_REVIEW";REVIEW_REQUIRED="REVIEW_REQUIRED"
class GovernedLLMDraftLifecycleStatus(str,Enum): ACTIVE="ACTIVE";SUPERSEDED="SUPERSEDED";INVALIDATED="INVALIDATED"

@dataclass(frozen=True)
class DraftReviewPolicyReference:
    policy_id:str;policy_version:str;human_review_required:bool;external_actionability_allowed:bool

@dataclass(frozen=True)
class GovernedLLMDraft:
    draft_id:str;draft_stream_id:str;version:int;predecessor:Optional[str]
    upstream_artifact_reference:UpstreamArtifactReference
    invocation_id:str;request_id:str;correlation_id:str;prompt_version:str
    provider:str;model:str;output_classification:str;review_status:DraftReviewStatus
    review_policy:DraftReviewPolicyReference;reviewable_content:str;reviewable_content_hash:str
    integrity_hash:str;policy_version:str;tenant_id:str;provenance:tuple[str,...]
    issued_at:datetime;issuance_attestation:str

@dataclass(frozen=True)
class GovernedLLMDraftLifecycleEvent:
    lifecycle_event_id:str;draft_id:str;draft_version:int;tenant_id:str
    prior_status:Optional[GovernedLLMDraftLifecycleStatus];resulting_status:GovernedLLMDraftLifecycleStatus
    reason_reference:str;actor_reference:str;policy_version:str;occurred_at:datetime
    stream_position:int;predecessor_event_id:Optional[str];previous_hash:Optional[str];integrity_hash:str
