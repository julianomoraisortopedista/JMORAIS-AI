from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional
from jmoraIs.gateway_input import UpstreamArtifactReference
class LLMGatewayError(RuntimeError):pass
class LLMPolicyRejected(LLMGatewayError):pass
class LLMProviderFailure(LLMGatewayError):pass
class LLMProviderTimeout(LLMProviderFailure):pass
class LLMRateLimited(LLMProviderFailure):pass
class PromptVersionConflict(LLMGatewayError):pass
class LLMProvider(str,Enum):OPENAI="OPENAI";AZURE_OPENAI="AZURE_OPENAI";ANTHROPIC="ANTHROPIC";GOOGLE_GEMINI="GOOGLE_GEMINI";LOCAL="LOCAL";MOCK="MOCK"
class LLMOutputClassification(str,Enum):DRAFT="DRAFT";REVIEW_REQUIRED="REVIEW_REQUIRED";BLOCKED="BLOCKED";APPROVED_FOR_REVIEW="APPROVED_FOR_REVIEW"
class InvocationStatus(str,Enum):SUCCEEDED="SUCCEEDED";FAILED="FAILED";TIMEOUT="TIMEOUT";RATE_LIMITED="RATE_LIMITED";BLOCKED="BLOCKED"
class PromptAuditType(str,Enum):PROMPT_REGISTERED="PROMPT_REGISTERED";INVOCATION="INVOCATION";PROVIDER_ERROR="PROVIDER_ERROR";RATE_LIMIT="RATE_LIMIT";TIMEOUT="TIMEOUT";POLICY_REJECTION="POLICY_REJECTION"
class InvocationContextPersistenceStatus(str,Enum):PERSISTED="PERSISTED";LEGACY_MISSING_INVOCATION_CONTEXT="LEGACY_MISSING_INVOCATION_CONTEXT"
class PersistedInputLinkStatus(str,Enum):PERSISTED="PERSISTED";LEGACY_MISSING_PERSISTED_GATEWAY_INPUT="LEGACY_MISSING_PERSISTED_GATEWAY_INPUT"
@dataclass(frozen=True)
class LLMInvocationContext:
    correlation_id:str;tenant_id:str;principal_id:str;purpose:str;policy_version:str;request_id:str;issued_at:datetime
@dataclass(frozen=True)
class LLMModel:
    provider:LLMProvider;model_id:str;model_version:str;input_cost_per_million:float;output_cost_per_million:float;enabled:bool;policy_version:str
@dataclass(frozen=True)
class PromptTemplate:
    template_id:str;name:str;purpose:str;template_text:str;allowed_input_types:tuple[str,...];output_schema_id:str;policy_version:str
@dataclass(frozen=True)
class PromptVersion:
    prompt_version_id:str;template_id:str;version:int;previous_version_id:Optional[str];template:PromptTemplate;prompt_hash:str;created_at:datetime;created_by:str
@dataclass(frozen=True)
class StructuredField:
    name:str;value:str;source_reference:str
@dataclass(frozen=True)
class CanonicalStructuredDTO:
    schema_id:str;schema_version:str;fields:tuple[StructuredField,...];policy_version:str;provenance_references:tuple[str,...]
@dataclass(frozen=True)
class ReviewPolicy:
    policy_id:str;policy_version:str;human_review_required:bool;external_actionability_allowed:bool=False
@dataclass(frozen=True)
class LLMRequest:
    request_id:str;prompt_version_id:str;model:LLMModel;input_dto:object;review_policy:ReviewPolicy;temperature:float;seed:Optional[int];max_output_tokens:int;policy_version:str;requested_at:datetime
@dataclass(frozen=True)
class ProviderRequest:
    request_id:str;model_id:str;system_prompt:str;canonical_payload:str;temperature:float;seed:Optional[int];max_output_tokens:int
@dataclass(frozen=True)
class ProviderResponse:
    provider_request_id:str;output_text:str;input_tokens:int;output_tokens:int;cached_tokens:int;latency_ms:int;provider_metadata_hash:str;refused:bool=False
@dataclass(frozen=True)
class TokenUsage:
    input_tokens:int;output_tokens:int;cached_tokens:int;total_tokens:int
@dataclass(frozen=True)
class CostReport:
    currency:str;input_cost:float;output_cost:float;total_cost:float;pricing_policy_version:str
@dataclass(frozen=True)
class LLMResponse:
    response_id:str;request_id:str;output_text:str;classification:LLMOutputClassification;token_usage:TokenUsage;cost:CostReport;provider_request_id:str;generated_at:datetime;externally_actionable:bool=False;reviewable_content_hash:Optional[str]=None
@dataclass(frozen=True)
class LLMInvocation:
    invocation_id:str;request_id:str;prompt_version_id:str;provider:LLMProvider;model_id:str;status:InvocationStatus;attempts:int;latency_ms:int;token_usage:Optional[TokenUsage];cost:Optional[CostReport];request_hash:str;response_hash:Optional[str];occurred_at:datetime;policy_version:str;correlation_id:Optional[str]=None;output_classification:Optional[LLMOutputClassification]=None;temperature:Optional[float]=None;seed:Optional[int]=None;upstream_reference:Optional[UpstreamArtifactReference]=None;reviewable_content_hash:Optional[str]=None;persisted_gateway_input_id:Optional[str]=None
@dataclass(frozen=True)
class PromptAudit:
    event_id:str;event_type:PromptAuditType;request_id:Optional[str];prompt_version_id:str;provider:Optional[LLMProvider];model_id:Optional[str];temperature:Optional[float];seed:Optional[int];token_usage:Optional[TokenUsage];cost:Optional[CostReport];latency_ms:Optional[int];retry_count:int;status:InvocationStatus;request_hash:Optional[str];response_hash:Optional[str];occurred_at:datetime;policy_version:str;correlation_id:Optional[str]=None
