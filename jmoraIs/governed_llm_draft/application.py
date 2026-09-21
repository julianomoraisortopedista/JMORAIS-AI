from __future__ import annotations
import hmac
import json
import re
from dataclasses import asdict,replace
from hashlib import sha256
from jmoraIs.gateway_input import PersistedGatewayInput,canonical_dto_hash
from jmoraIs.llm_gateway.domain import InvocationStatus,LLMInvocation,LLMOutputClassification,LLMResponse,ReviewPolicy
from jmoraIs.tenancy.context import current_tenant_context
from .domain import *

class GovernedDraftAttestor:
    def __init__(self,key:bytes):
        if not isinstance(key,bytes) or len(key)<32:raise DraftBoundaryRejected("draft attestation key must contain at least 32 bytes")
        self._key=key
    def sign(self,value):return hmac.new(self._key,_attestation_material(value),sha256).hexdigest()
    def verify(self,value):return isinstance(value,GovernedLLMDraft) and bool(value.issuance_attestation) and hmac.compare_digest(value.issuance_attestation,self.sign(value))

class ReviewableContentRedactor:
    _patterns=(
        re.compile(r"(?i)\b(?:bearer\s+|sk-)[A-Za-z0-9._-]+"),
        re.compile(r"(?i)\b(?:password|api[_-]?key|secret|token)\s*[:=]\s*\S+"),
        re.compile(r"(?i)\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b"),
        re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"),
    )
    def redact(self,content:str)->str:
        if not isinstance(content,str) or not content:raise DraftBoundaryRejected("reviewable content is required")
        result=content
        for pattern in self._patterns:result=pattern.sub("[REDACTED]",result)
        return result

class GovernedLLMDraftIssuanceService:
    ELIGIBLE={LLMOutputClassification.DRAFT,LLMOutputClassification.REVIEW_REQUIRED,LLMOutputClassification.APPROVED_FOR_REVIEW}
    def __init__(self,repository,invocations,contexts,input_attestor,draft_attestor,*,clock,redactor=None):
        self._repository=repository;self._invocations=invocations;self._contexts=contexts;self._input_attestor=input_attestor;self._draft_attestor=draft_attestor;self._clock=clock;self._redactor=redactor or ReviewableContentRedactor()
    def issue(self,persisted_input,response,review_policy):
        tenant=current_tenant_context()
        if not isinstance(persisted_input,PersistedGatewayInput) or not self._input_attestor.verify(persisted_input) or canonical_dto_hash(persisted_input.dto)!=persisted_input.dto_hash:raise DraftBoundaryRejected("trusted persisted Gateway input is required")
        if persisted_input.reference.tenant_id!=tenant.tenant_id:raise DraftBoundaryRejected("draft tenant mismatch")
        if not isinstance(response,LLMResponse) or not isinstance(review_policy,ReviewPolicy):raise DraftBoundaryRejected("canonical Gateway response and review policy are required")
        history=self._invocations.history(response.request_id)
        if len(history)!=1:raise DraftBoundaryRejected("exact persisted LLM invocation is required")
        invocation=history[0];context=self._contexts.get(response.request_id)
        self._validate_linkage(persisted_input,response,review_policy,invocation,context,tenant)
        content=self._redactor.redact(response.output_text);content_hash=sha256(content.encode("utf-8")).hexdigest()
        if content_hash!=response.reviewable_content_hash or content_hash!=invocation.reviewable_content_hash:raise DraftBoundaryRejected("reviewable content integrity mismatch")
        stream="draft_stream_"+sha256((persisted_input.reference.artifact_type+"|"+persisted_input.reference.artifact_id).encode()).hexdigest()
        latest=self._repository.latest(stream);version=latest.version+1 if latest else 1;predecessor=latest.draft_id if latest else None;issued=self._clock()
        policy=DraftReviewPolicyReference(review_policy.policy_id,review_policy.policy_version,review_policy.human_review_required,review_policy.external_actionability_allowed)
        review_status=DraftReviewStatus.PENDING_REVIEW if response.classification is LLMOutputClassification.APPROVED_FOR_REVIEW else DraftReviewStatus.REVIEW_REQUIRED
        provenance=("invocation:"+invocation.invocation_id,"upstream:"+persisted_input.reference.artifact_id,"prompt:"+invocation.prompt_version_id)
        draft_id="draft_"+sha256((stream+"|"+str(version)+"|"+content_hash).encode()).hexdigest()
        unsigned=GovernedLLMDraft(draft_id,stream,version,predecessor,persisted_input.reference,invocation.invocation_id,response.request_id,context.correlation_id,invocation.prompt_version_id,invocation.provider.value,invocation.model_id,response.classification.value,review_status,policy,content,content_hash,"",invocation.policy_version,tenant.tenant_id,provenance,issued,"")
        integrity=_integrity_hash(unsigned);with_integrity=replace(unsigned,integrity_hash=integrity)
        result=replace(with_integrity,issuance_attestation=self._draft_attestor.sign(with_integrity))
        from .lifecycle import lifecycle_event
        active=lifecycle_event(result,GovernedLLMDraftLifecycleStatus.ACTIVE,"CANONICAL_ISSUANCE","governed-draft-issuance",result.policy_version,issued)
        supersession=None
        if latest is not None:
            old_history=self._repository.lifecycle_history(latest.draft_id)
            supersession=lifecycle_event(latest,GovernedLLMDraftLifecycleStatus.SUPERSEDED,"REPLACED_BY:"+result.draft_id,"governed-draft-issuance",result.policy_version,issued,old_history)
        self._repository.append_with_lifecycle(result,active,supersession);return result
    @staticmethod
    def _validate_linkage(bound,response,policy,invocation,context,tenant):
        if not isinstance(invocation,LLMInvocation) or invocation.status is not InvocationStatus.SUCCEEDED or invocation.output_classification not in GovernedLLMDraftIssuanceService.ELIGIBLE:raise DraftBoundaryRejected("invocation is not draft eligible")
        if response.classification not in GovernedLLMDraftIssuanceService.ELIGIBLE or response.classification is not invocation.output_classification:raise DraftBoundaryRejected("blocked or mismatched output cannot emit a draft")
        if response.request_id!=invocation.request_id or response.response_id!="resp_"+str(invocation.response_hash):raise DraftBoundaryRejected("Gateway response does not match invocation")
        if invocation.upstream_reference!=bound.reference:raise DraftBoundaryRejected("invocation upstream reference mismatch")
        if context is None or context.request_id!=invocation.request_id or context.correlation_id!=invocation.correlation_id or context.tenant_id!=tenant.tenant_id:raise DraftBoundaryRejected("invocation context linkage mismatch")
        if not policy.human_review_required or policy.external_actionability_allowed or policy.policy_version!=invocation.policy_version:raise DraftBoundaryRejected("review policy is not eligible")

def _integrity_hash(value):
    material=asdict(value);material["integrity_hash"]="";material["issuance_attestation"]=""
    return sha256(json.dumps(material,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()
def _attestation_material(value):return (value.integrity_hash+"|"+value.reviewable_content_hash+"|"+value.draft_id+"|"+value.tenant_id).encode()
def validate_draft_integrity(value,attestor):
    return isinstance(value,GovernedLLMDraft) and value.reviewable_content_hash==sha256(value.reviewable_content.encode("utf-8")).hexdigest() and value.integrity_hash==_integrity_hash(value) and attestor.verify(value)
