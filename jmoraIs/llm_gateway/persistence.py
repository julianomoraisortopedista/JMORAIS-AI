from __future__ import annotations
import json
from dataclasses import fields,is_dataclass
from datetime import datetime
from enum import Enum
from hashlib import sha256
from sqlalchemy import text
from jmoraIs.tenancy.context import current_tenant_context
from jmoraIs.tenancy.domain import MissingTenantContext
from . import domain
from jmoraIs.gateway_input import UpstreamArtifactReference
from .domain import *
_TYPES={n:v for n,v in vars(domain).items() if isinstance(v,type) and is_dataclass(v)};_TYPES["UpstreamArtifactReference"]=UpstreamArtifactReference;_ENUMS={n:v for n,v in vars(domain).items() if isinstance(v,type) and issubclass(v,Enum)}
class LLMGatewayJsonCodec:
    schema_version=1
    def encode(self,v):
        if is_dataclass(v):return {"__type__":type(v).__name__,**{f.name:self.encode(getattr(v,f.name)) for f in fields(v)}}
        if isinstance(v,Enum):return {"__enum__":type(v).__name__,"value":v.value}
        if isinstance(v,datetime):return {"__datetime__":v.isoformat()}
        if isinstance(v,tuple):return {"__tuple__":[self.encode(x) for x in v]}
        return v
    def decode(self,v):
        if isinstance(v,list):return tuple(self.decode(x) for x in v)
        if not isinstance(v,dict):return v
        if "__enum__" in v:return _ENUMS[v["__enum__"]](v["value"])
        if "__datetime__" in v:return datetime.fromisoformat(v["__datetime__"])
        if "__tuple__" in v:return tuple(self.decode(x) for x in v["__tuple__"])
        if "__type__" in v:return _TYPES[v["__type__"]](**{k:self.decode(x) for k,x in v.items() if k!="__type__"})
        return {k:self.decode(x) for k,x in v.items()}
class PostgreSQLPromptRepository:
    def __init__(self,engine,codec=None):self._engine=engine;self._codec=codec or LLMGatewayJsonCodec()
    def append(self,v):
        with self._engine.begin() as c:
            c.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),{"key":"prompt:"+v.template_id});latest=c.execute(text("SELECT prompt_version_id,version FROM llm_prompt_versions WHERE template_id=:id ORDER BY version DESC LIMIT 1"),{"id":v.template_id}).mappings().first()
            if latest and (v.previous_version_id!=latest["prompt_version_id"] or v.version!=latest["version"]+1):raise PromptVersionConflict("invalid prompt version chain")
            if not latest and (v.version!=1 or v.previous_version_id is not None):raise PromptVersionConflict("prompt history must begin at version 1")
            c.execute(text("INSERT INTO llm_prompt_versions(prompt_version_id,template_id,version,previous_version_id,prompt_hash,policy_version,created_at,payload,schema_version) VALUES(:id,:template,:version,:previous,:hash,:policy,:at,CAST(:payload AS jsonb),:schema)"),{"id":v.prompt_version_id,"template":v.template_id,"version":v.version,"previous":v.previous_version_id,"hash":v.prompt_hash,"policy":v.template.policy_version,"at":v.created_at,"payload":json.dumps(self._codec.encode(v),sort_keys=True,separators=(",",":")),"schema":self._codec.schema_version})
    def get(self,identifier):
        with self._engine.connect() as c:payload=c.execute(text("SELECT payload FROM llm_prompt_versions WHERE prompt_version_id=:id"),{"id":identifier}).scalar_one_or_none()
        return self._codec.decode(payload) if payload else None
    def history(self,template_id):
        with self._engine.connect() as c:rows=c.execute(text("SELECT payload FROM llm_prompt_versions WHERE template_id=:id ORDER BY version"),{"id":template_id}).scalars().all()
        return tuple(self._codec.decode(x) for x in rows)
class PostgreSQLPromptAuditRepository:
    def __init__(self,engine,codec=None):self._engine=engine;self._codec=codec or LLMGatewayJsonCodec()
    def append(self,e):
        if e.request_id and not e.correlation_id:raise LLMPolicyRejected("governed prompt audit requires correlation ID")
        with self._engine.begin() as c:
            if e.request_id:
                linkage=c.execute(text("SELECT i.correlation_id,i.temperature,i.seed,c.principal_id,c.purpose,c.policy_version AS context_policy FROM llm_invocations i JOIN llm_invocation_contexts c ON c.request_id=i.request_id WHERE i.request_id=:id ORDER BY i.sequence_id DESC LIMIT 1"),{"id":e.request_id}).mappings().first()
                if not linkage or linkage["correlation_id"]!=e.correlation_id:raise LLMPolicyRejected("invocation and prompt-audit correlation mismatch")
                if linkage["context_policy"]!=e.policy_version:raise LLMPolicyRejected("invocation context and prompt-audit policy mismatch")
                if linkage["temperature"]!=e.temperature or linkage["seed"]!=e.seed:raise LLMPolicyRejected("invocation and prompt-audit generation configuration mismatch")
            c.execute(text("INSERT INTO llm_prompt_audit(event_id,event_type,request_id,prompt_version_id,provider,model_id,correlation_id,occurred_at,policy_version,payload,schema_version) VALUES(:id,:type,:request,:prompt,:provider,:model,:correlation,:at,:policy,CAST(:payload AS jsonb),:schema)"),{"id":e.event_id,"type":e.event_type.value,"request":e.request_id,"prompt":e.prompt_version_id,"provider":e.provider.value if e.provider else None,"model":e.model_id,"correlation":e.correlation_id,"at":e.occurred_at,"policy":e.policy_version,"payload":json.dumps(self._codec.encode(e),sort_keys=True,separators=(",",":")),"schema":self._codec.schema_version})
    def history(self,request_id):
        with self._engine.connect() as c:rows=c.execute(text("SELECT payload FROM llm_prompt_audit WHERE request_id=:id ORDER BY sequence_id"),{"id":request_id}).scalars().all()
        return tuple(self._codec.decode(x) for x in rows)
    def history_by_correlation(self,correlation_id):
        with self._engine.connect() as c:rows=c.execute(text("SELECT payload FROM llm_prompt_audit WHERE correlation_id=:id ORDER BY sequence_id"),{"id":correlation_id}).scalars().all()
        return tuple(self._codec.decode(x) for x in rows)
class PostgreSQLInvocationRepository:
    def __init__(self,engine,codec=None):self._engine=engine;self._codec=codec or LLMGatewayJsonCodec()
    def append(self,v):
        if not v.correlation_id:raise LLMPolicyRejected("governed invocation requires correlation ID")
        if v.temperature is None or not 0<=v.temperature<=2:raise LLMPolicyRejected("governed invocation requires valid generation configuration")
        if v.status in {InvocationStatus.SUCCEEDED,InvocationStatus.BLOCKED} and v.output_classification is None:raise LLMPolicyRejected("completed invocation requires output classification")
        if v.output_classification is LLMOutputClassification.BLOCKED and v.status is not InvocationStatus.BLOCKED:raise LLMPolicyRejected("classification and invocation status mismatch")
        if v.output_classification not in {None,LLMOutputClassification.BLOCKED} and v.status is not InvocationStatus.SUCCEEDED:raise LLMPolicyRejected("classification and invocation status mismatch")
        if v.upstream_reference is not None and v.status is InvocationStatus.SUCCEEDED and (not v.reviewable_content_hash or len(v.reviewable_content_hash)!=64):raise LLMPolicyRejected("persisted-input invocation requires reviewable content hash")
        if v.upstream_reference is not None and v.upstream_reference.tenant_id!=current_tenant_context().tenant_id:raise LLMPolicyRejected("invocation upstream tenant mismatch")
        if v.upstream_reference is not None and not v.persisted_gateway_input_id:raise LLMPolicyRejected("persisted-input invocation requires canonical persisted input linkage")
        with self._engine.begin() as c:
            context=c.execute(text("SELECT correlation_id,policy_version FROM llm_invocation_contexts WHERE request_id=:id"),{"id":v.request_id}).mappings().first()
            if not context:raise LLMPolicyRejected("persisted invocation context is required")
            if context["correlation_id"]!=v.correlation_id:raise LLMPolicyRejected("invocation context correlation mismatch")
            if context["policy_version"]!=v.policy_version:raise LLMPolicyRejected("invocation context policy mismatch")
            if v.persisted_gateway_input_id:
                persisted=c.execute(text("SELECT tenant_id,artifact_type,artifact_id,artifact_version FROM persisted_gateway_inputs WHERE persisted_gateway_input_id=:id"),{"id":v.persisted_gateway_input_id}).mappings().first()
                if not persisted or (persisted["tenant_id"],persisted["artifact_type"],persisted["artifact_id"],persisted["artifact_version"])!=(v.upstream_reference.tenant_id,v.upstream_reference.artifact_type,v.upstream_reference.artifact_id,v.upstream_reference.artifact_version):raise LLMPolicyRejected("invocation persisted-input linkage mismatch")
            c.execute(text("INSERT INTO llm_invocations(invocation_id,request_id,prompt_version_id,provider,model_id,status,correlation_id,output_classification,temperature,seed,upstream_artifact_type,upstream_artifact_id,upstream_artifact_version,persisted_gateway_input_id,reviewable_content_hash,occurred_at,policy_version,payload,schema_version) VALUES(:id,:request,:prompt,:provider,:model,:status,:correlation,:classification,:temperature,:seed,:upstream_type,:upstream_id,:upstream_version,:persisted_input,:content_hash,:at,:policy,CAST(:payload AS jsonb),:schema)"),{"id":v.invocation_id,"request":v.request_id,"prompt":v.prompt_version_id,"provider":v.provider.value,"model":v.model_id,"status":v.status.value,"correlation":v.correlation_id,"classification":v.output_classification.value if v.output_classification else None,"temperature":v.temperature,"seed":v.seed,"upstream_type":v.upstream_reference.artifact_type if v.upstream_reference else None,"upstream_id":v.upstream_reference.artifact_id if v.upstream_reference else None,"upstream_version":v.upstream_reference.artifact_version if v.upstream_reference else None,"persisted_input":v.persisted_gateway_input_id,"content_hash":v.reviewable_content_hash,"at":v.occurred_at,"policy":v.policy_version,"payload":json.dumps(self._codec.encode(v),sort_keys=True,separators=(",",":")),"schema":self._codec.schema_version})
    def history(self,request_id):
        with self._engine.connect() as c:rows=c.execute(text("SELECT payload FROM llm_invocations WHERE request_id=:id ORDER BY sequence_id"),{"id":request_id}).scalars().all()
        return tuple(self._codec.decode(x) for x in rows)
    def history_by_correlation(self,correlation_id):
        with self._engine.connect() as c:rows=c.execute(text("SELECT payload FROM llm_invocations WHERE correlation_id=:id ORDER BY sequence_id"),{"id":correlation_id}).scalars().all()
        return tuple(self._codec.decode(x) for x in rows)
    def persisted_input_status(self,invocation_id):
        with self._engine.connect() as c:value=c.execute(text("SELECT persisted_gateway_input_id FROM llm_invocations WHERE invocation_id=:id"),{"id":invocation_id}).scalar_one_or_none()
        return PersistedInputLinkStatus.PERSISTED if value else PersistedInputLinkStatus.LEGACY_MISSING_PERSISTED_GATEWAY_INPUT
class PostgreSQLLLMInvocationContextRepository:
    def __init__(self,engine):self._engine=engine
    @staticmethod
    def _hash(value):
        material="|".join((value.request_id,value.correlation_id,value.tenant_id,value.principal_id,value.purpose,value.policy_version,value.issued_at.isoformat()))
        return sha256(material.encode()).hexdigest()
    def append(self,value):
        if not isinstance(value,LLMInvocationContext):raise LLMPolicyRejected("trusted invocation context is required")
        if value.issued_at.tzinfo is None:raise LLMPolicyRejected("invocation context timestamp must be timezone-aware")
        for name in ("request_id","correlation_id","tenant_id","principal_id","purpose","policy_version"):
            if not getattr(value,name).strip():raise LLMPolicyRejected("invocation context metadata is incomplete")
        if value.request_id==value.correlation_id:raise LLMPolicyRejected("request and correlation identities must remain distinct")
        try:trusted=current_tenant_context()
        except MissingTenantContext as exc:raise LLMPolicyRejected("trusted tenant context is required for invocation context persistence") from exc
        expected=(trusted.tenant_id,trusted.principal_id,trusted.purpose,trusted.policy_version,trusted.correlation_id)
        actual=(value.tenant_id,value.principal_id,value.purpose,value.policy_version,value.correlation_id)
        if actual!=expected:raise LLMPolicyRejected("invocation context does not match trusted tenant context")
        with self._engine.begin() as c:
            c.execute(text("INSERT INTO llm_invocation_contexts(request_id,correlation_id,tenant_id,principal_id,purpose,policy_version,issued_at,integrity_hash) VALUES(:request,:correlation,:tenant,:principal,:purpose,:policy,:issued,:hash)"),{"request":value.request_id,"correlation":value.correlation_id,"tenant":value.tenant_id,"principal":value.principal_id,"purpose":value.purpose,"policy":value.policy_version,"issued":value.issued_at,"hash":self._hash(value)})
    def get(self,request_id):
        with self._engine.connect() as c:row=c.execute(text("SELECT request_id,correlation_id,tenant_id,principal_id,purpose,policy_version,issued_at,integrity_hash FROM llm_invocation_contexts WHERE request_id=:id"),{"id":request_id}).mappings().first()
        return self._decode(row)
    def history_by_correlation(self,correlation_id):
        with self._engine.connect() as c:rows=c.execute(text("SELECT request_id,correlation_id,tenant_id,principal_id,purpose,policy_version,issued_at,integrity_hash FROM llm_invocation_contexts WHERE correlation_id=:id ORDER BY sequence_id"),{"id":correlation_id}).mappings().all()
        return tuple(self._decode(x) for x in rows)
    def status(self,request_id):return InvocationContextPersistenceStatus.PERSISTED if self.get(request_id) else InvocationContextPersistenceStatus.LEGACY_MISSING_INVOCATION_CONTEXT
    def _decode(self,row):
        if row is None:return None
        value=LLMInvocationContext(row["correlation_id"],row["tenant_id"],row["principal_id"],row["purpose"],row["policy_version"],row["request_id"],row["issued_at"])
        if row["integrity_hash"]!=self._hash(value):raise LLMPolicyRejected("invocation context integrity mismatch")
        return value
