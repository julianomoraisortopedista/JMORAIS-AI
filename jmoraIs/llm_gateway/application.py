from __future__ import annotations
import json
import re
from dataclasses import asdict,is_dataclass
from hashlib import sha256
from jmoraIs.audit_defense.domain import AuditDefense
from jmoraIs.medical_documents.domain import MedicalDocument
from jmoraIs.orthopedic_intelligence.domain import OrthopedicAssessment
from jmoraIs.reasoning_input.domain import ClinicalReasoningInput
from jmoraIs.tenancy.context import current_tenant_context
from jmoraIs.tenancy.domain import MissingTenantContext
from jmoraIs.gateway_input import PersistedGatewayInput, canonical_dto_hash
from .domain import *
class PromptGovernanceService:
    def __init__(self,repository,audit,*,clock):self._repository=repository;self._audit=audit;self._clock=clock
    def register(self,template,*,created_by):
        if not isinstance(template,PromptTemplate) or not template.policy_version or not created_by.strip():raise LLMPolicyRejected("prompt template, policy, and author are required")
        if CanonicalDTOEncoder.contains_secret(template.template_text):raise LLMPolicyRejected("prompt templates cannot contain secrets")
        history=self._repository.history(template.template_id);version=len(history)+1;previous=history[-1].prompt_version_id if history else None;digest=self._hash(template)
        value=PromptVersion("prompt_"+digest,template.template_id,version,previous,template,digest,self._clock(),created_by);self._repository.append(value)
        self._audit.append(PromptAudit("pa_"+digest,PromptAuditType.PROMPT_REGISTERED,None,value.prompt_version_id,None,None,None,None,None,None,None,0,InvocationStatus.SUCCEEDED,digest,None,self._clock(),template.policy_version));return value
    @staticmethod
    def _hash(template):return sha256(json.dumps(asdict(template),sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()
class CanonicalDTOEncoder:
    TYPES=(MedicalDocument,AuditDefense,OrthopedicAssessment,ClinicalReasoningInput,CanonicalStructuredDTO)
    FORBIDDEN_KEYS=("patient_name","full_name","cpf","email","phone","telephone","address","password","secret","token","api_key","authorization")
    FORBIDDEN_VALUES=("bearer ","sk-","api_key=","password=")
    SECRET_PATTERN=re.compile(r"(?:bearer\s+|api_key\s*=|password\s*=|(?<![a-z0-9])sk-[a-z0-9])",re.IGNORECASE)
    @classmethod
    def contains_secret(cls,value):return isinstance(value,str) and cls.SECRET_PATTERN.search(value) is not None
    def encode(self,value):
        if type(value) not in self.TYPES or hasattr(value,"__table__"):raise LLMPolicyRejected("unsupported or infrastructure DTO")
        if isinstance(value,MedicalDocument) and (not value.validation.valid or not value.pseudonymous_patient_id.startswith("pt_")):raise LLMPolicyRejected("medical document is not safe for gateway input")
        if isinstance(value,CanonicalStructuredDTO):
            for field in value.fields:
                lowered=field.name.casefold()
                if any(token==lowered or lowered.endswith("_"+token) for token in self.FORBIDDEN_KEYS) or self.contains_secret(field.value):raise LLMPolicyRejected("patient identity, secret, or token field is forbidden")
        data=asdict(value);self._scan(data);return json.dumps(data,sort_keys=True,separators=(",",":"),default=self._default)
    def _scan(self,value,path=""):
        if isinstance(value,dict):
            for key,item in value.items():
                lowered=str(key).casefold()
                if any(token==lowered or lowered.endswith("_"+token) for token in self.FORBIDDEN_KEYS):raise LLMPolicyRejected("patient identity, secret, or token field is forbidden")
                self._scan(item,path+"."+str(key))
        elif isinstance(value,(list,tuple)):
            for item in value:self._scan(item,path)
        elif self.contains_secret(value):raise LLMPolicyRejected("secret-like value is forbidden")
    @staticmethod
    def _default(value):return value.value if isinstance(value,Enum) else value.isoformat() if isinstance(value,datetime) else str(value)
class CanonicalLLMGateway:
    POLICY="MIP-10.1"
    def __init__(self,prompts,audit,invocations,contexts,providers,*,clock,max_retries=2,encoder=None,persisted_input_attestor=None,persisted_inputs=None):self._prompts=prompts;self._audit=audit;self._invocations=invocations;self._contexts=contexts;self._providers={x.provider:x for x in providers};self._clock=clock;self._max_retries=max_retries;self._encoder=encoder or CanonicalDTOEncoder();self._persisted_input_attestor=persisted_input_attestor;self._persisted_inputs=persisted_inputs
    def invoke(self,request):
        self._guard(request);context=self._trusted_context(request);prompt=self._prompts.get(request.prompt_version_id)
        if not isinstance(prompt,PromptVersion) or PromptGovernanceService._hash(prompt.template)!=prompt.prompt_hash:raise LLMPolicyRejected("prompt version is missing or integrity-invalid")
        if type(request.input_dto).__name__ not in prompt.template.allowed_input_types:raise LLMPolicyRejected("input DTO is not allowed by prompt policy")
        payload=self._encoder.encode(request.input_dto);request_hash=self._hash(request.request_id,prompt.prompt_hash,payload,request.model.model_id,request.policy_version);adapter=self._providers.get(request.model.provider)
        if adapter is None or not request.model.enabled:raise LLMPolicyRejected("provider or model is not enabled")
        self._contexts.append(context)
        provider_request=ProviderRequest(request.request_id,request.model.model_id,prompt.template.template_text,payload,request.temperature,request.seed,request.max_output_tokens)
        attempts=0;last=None
        while attempts<=self._max_retries:
            attempts+=1
            try:
                raw=adapter.invoke(provider_request);return self._success(request,prompt,raw,request_hash,attempts,context)
            except (LLMProviderTimeout,LLMRateLimited,LLMProviderFailure) as exc:
                last=exc
                if attempts>self._max_retries:break
        self._failure(request,prompt,request_hash,attempts,last,context);raise last
    def invoke_persisted(self,request):
        if not isinstance(request,LLMRequest) or not isinstance(request.input_dto,PersistedGatewayInput):raise LLMPolicyRejected("review-eligible invocation requires PersistedGatewayInput")
        bound=request.input_dto
        if self._persisted_input_attestor is None or not self._persisted_input_attestor.verify(bound):raise LLMPolicyRejected("persisted Gateway input attestation is invalid")
        if canonical_dto_hash(bound.dto)!=bound.dto_hash:raise LLMPolicyRejected("persisted Gateway DTO integrity mismatch")
        expected={MedicalDocument:"MedicalDocument",AuditDefense:"AuditDefense",OrthopedicAssessment:"OrthopedicAssessment",ClinicalReasoningInput:"ClinicalReasoningInput"}.get(type(bound.dto))
        if expected is None or bound.reference.artifact_type!=expected:raise LLMPolicyRejected("upstream artifact type does not match DTO type")
        tenant=current_tenant_context()
        if bound.reference.tenant_id!=tenant.tenant_id:raise LLMPolicyRejected("cross-tenant persisted Gateway input is forbidden")
        unwrapped=LLMRequest(request.request_id,request.prompt_version_id,request.model,bound.dto,request.review_policy,request.temperature,request.seed,request.max_output_tokens,request.policy_version,request.requested_at)
        if self._persisted_inputs is None:raise LLMPolicyRejected("persisted Gateway input repository is required")
        return self._invoke_bound(unwrapped,bound.reference,bound)
    def _invoke_bound(self,request,reference,persisted_input=None):
        self._guard(request);context=self._trusted_context(request);prompt=self._prompts.get(request.prompt_version_id)
        if not isinstance(prompt,PromptVersion) or PromptGovernanceService._hash(prompt.template)!=prompt.prompt_hash:raise LLMPolicyRejected("prompt version is missing or integrity-invalid")
        if type(request.input_dto).__name__ not in prompt.template.allowed_input_types:raise LLMPolicyRejected("input DTO is not allowed by prompt policy")
        payload=self._encoder.encode(request.input_dto);request_hash=self._hash(request.request_id,prompt.prompt_hash,payload,request.model.model_id,request.policy_version);adapter=self._providers.get(request.model.provider)
        if adapter is None or not request.model.enabled:raise LLMPolicyRejected("provider or model is not enabled")
        self._contexts.append(context);persisted_record=self._persisted_inputs.persist(persisted_input) if persisted_input is not None else None;provider_request=ProviderRequest(request.request_id,request.model.model_id,prompt.template.template_text,payload,request.temperature,request.seed,request.max_output_tokens)
        attempts=0;last=None
        while attempts<=self._max_retries:
            attempts+=1
            try:return self._success(request,prompt,adapter.invoke(provider_request),request_hash,attempts,context,reference,persisted_record.persisted_gateway_input_id if persisted_record else None)
            except (LLMProviderTimeout,LLMRateLimited,LLMProviderFailure) as exc:
                last=exc
                if attempts>self._max_retries:break
        self._failure(request,prompt,request_hash,attempts,last,context,reference,persisted_record.persisted_gateway_input_id if persisted_record else None);raise last
    def _trusted_context(self,r):
        try:tenant=current_tenant_context()
        except MissingTenantContext as exc:raise LLMPolicyRejected("trusted invocation context is required") from exc
        correlation=tenant.correlation_id.strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{7,127}",correlation):raise LLMPolicyRejected("correlation ID format is invalid")
        lowered=correlation.casefold()
        if any(token in lowered for token in ("pt_","cpf","email","@","bearer","sk-","password","token","secret")):raise LLMPolicyRejected("correlation ID contains prohibited data")
        if correlation==r.request_id:raise LLMPolicyRejected("request and correlation identities must remain distinct")
        return LLMInvocationContext(correlation,tenant.tenant_id,tenant.principal_id,tenant.purpose,tenant.policy_version,r.request_id,self._clock())
    def _guard(self,r):
        if not isinstance(r,LLMRequest) or not r.policy_version or not isinstance(r.review_policy,ReviewPolicy) or not r.review_policy.policy_version:raise LLMPolicyRejected("request and review policy are mandatory")
        if not r.review_policy.human_review_required or r.review_policy.external_actionability_allowed:raise LLMPolicyRejected("human review is mandatory and external actionability forbidden")
        if r.policy_version!=self.POLICY or r.model.policy_version!=self.POLICY:raise LLMPolicyRejected("gateway policy mismatch")
        if not 0<=r.temperature<=2 or r.max_output_tokens<1:raise LLMPolicyRejected("generation parameters are invalid")
    def _success(self,r,prompt,raw,request_hash,attempts,context,upstream_reference=None,persisted_gateway_input_id=None):
        if not isinstance(raw,ProviderResponse) or min(raw.input_tokens,raw.output_tokens,raw.cached_tokens,raw.latency_ms)<0:raise LLMProviderFailure("invalid provider response")
        usage=TokenUsage(raw.input_tokens,raw.output_tokens,raw.cached_tokens,raw.input_tokens+raw.output_tokens);cost=self._cost(r.model,usage);lowered=raw.output_text.casefold();secret=any(x in lowered for x in ("sk-","bearer ","password=","api_key="));identity=any(x in lowered for x in ("cpf","patient_name","nome completo","e-mail","email"));classification=LLMOutputClassification.BLOCKED if raw.refused or secret else LLMOutputClassification.REVIEW_REQUIRED if identity else LLMOutputClassification.APPROVED_FOR_REVIEW;response_hash=self._hash(raw.output_text,raw.provider_metadata_hash);safe_output="[BLOCKED]" if secret else raw.output_text
        content_hash=sha256(safe_output.encode("utf-8")).hexdigest();response=LLMResponse("resp_"+response_hash,r.request_id,safe_output,classification,usage,cost,raw.provider_request_id,self._clock(),False,content_hash);status=InvocationStatus.BLOCKED if classification is LLMOutputClassification.BLOCKED else InvocationStatus.SUCCEEDED
        invocation=LLMInvocation("inv_"+self._hash(r.request_id,str(attempts),response_hash),r.request_id,prompt.prompt_version_id,r.model.provider,r.model.model_id,status,attempts,raw.latency_ms,usage,cost,request_hash,response_hash,self._clock(),self.POLICY,context.correlation_id,classification,r.temperature,r.seed,upstream_reference,content_hash,persisted_gateway_input_id);self._invocations.append(invocation);self._audit_event(r,prompt,status,usage,cost,raw.latency_ms,attempts-1,request_hash,response_hash,context=context);return response
    def _failure(self,r,prompt,request_hash,attempts,error,context,upstream_reference=None,persisted_gateway_input_id=None):
        status=InvocationStatus.TIMEOUT if isinstance(error,LLMProviderTimeout) else InvocationStatus.RATE_LIMITED if isinstance(error,LLMRateLimited) else InvocationStatus.FAILED;kind=PromptAuditType.TIMEOUT if status is InvocationStatus.TIMEOUT else PromptAuditType.RATE_LIMIT if status is InvocationStatus.RATE_LIMITED else PromptAuditType.PROVIDER_ERROR
        inv=LLMInvocation("inv_"+self._hash(r.request_id,str(attempts),status.value),r.request_id,prompt.prompt_version_id,r.model.provider,r.model.model_id,status,attempts,0,None,None,request_hash,None,self._clock(),self.POLICY,context.correlation_id,None,r.temperature,r.seed,upstream_reference,None,persisted_gateway_input_id);self._invocations.append(inv);self._audit_event(r,prompt,status,None,None,None,attempts-1,request_hash,None,kind,context)
    def _audit_event(self,r,prompt,status,usage,cost,latency,retries,request_hash,response_hash,kind=PromptAuditType.INVOCATION,context=None):
        event=PromptAudit("pa_"+self._hash(r.request_id,status.value,str(retries),request_hash),kind,r.request_id,prompt.prompt_version_id,r.model.provider,r.model.model_id,r.temperature,r.seed,usage,cost,latency,retries,status,request_hash,response_hash,self._clock(),self.POLICY,context.correlation_id if context else None);self._audit.append(event)
    @staticmethod
    def _cost(model,usage):
        incoming=round(usage.input_tokens*model.input_cost_per_million/1_000_000,8);outgoing=round(usage.output_tokens*model.output_cost_per_million/1_000_000,8);return CostReport("USD",incoming,outgoing,round(incoming+outgoing,8),model.policy_version)
    @staticmethod
    def _hash(*parts):return sha256("|".join(parts).encode()).hexdigest()
