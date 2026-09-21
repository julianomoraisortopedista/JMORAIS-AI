from __future__ import annotations
import json
from dataclasses import fields,is_dataclass
from datetime import datetime
from enum import Enum
from sqlalchemy import text
from jmoraIs.gateway_input import UpstreamArtifactReference
from jmoraIs.tenancy.context import current_tenant_context
from . import domain
from .application import validate_draft_integrity
from .lifecycle import validate_lifecycle_chain
from .domain import *
_TYPES={n:v for n,v in vars(domain).items() if isinstance(v,type) and is_dataclass(v)};_TYPES["UpstreamArtifactReference"]=UpstreamArtifactReference
_ENUMS={n:v for n,v in vars(domain).items() if isinstance(v,type) and issubclass(v,Enum)}
class GovernedLLMDraftJsonCodec:
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
class PostgreSQLGovernedLLMDraftRepository:
    def __init__(self,engine,attestor,codec=None):self._engine=engine;self._attestor=attestor;self._codec=codec or GovernedLLMDraftJsonCodec()
    def append(self,v):raise DraftBoundaryRejected("canonical draft issuance requires atomic ACTIVE lifecycle")
    def append_with_lifecycle(self,v,active,supersession=None):
        if not validate_draft_integrity(v,self._attestor):raise DraftBoundaryRejected("draft integrity or issuance attestation is invalid")
        if v.tenant_id!=current_tenant_context().tenant_id or v.upstream_artifact_reference.tenant_id!=v.tenant_id:raise DraftBoundaryRejected("draft tenant mismatch")
        with self._engine.begin() as c:
            c.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),{"key":"governed_llm_draft:"+v.draft_stream_id})
            latest=c.execute(text("SELECT draft_id,version FROM governed_llm_drafts WHERE draft_stream_id=:s ORDER BY version DESC LIMIT 1"),{"s":v.draft_stream_id}).mappings().first()
            if latest and (v.predecessor!=latest["draft_id"] or v.version!=latest["version"]+1):raise DraftVersionConflict("invalid draft version chain")
            if not latest and (v.version!=1 or v.predecessor is not None):raise DraftVersionConflict("draft history must begin at version 1")
            if active.draft_id!=v.draft_id or active.tenant_id!=v.tenant_id or not validate_lifecycle_chain((active,)):raise DraftBoundaryRejected("valid ACTIVE genesis is required")
            if latest:
                old=self._lifecycle_history(c,latest["draft_id"])
                if supersession is None or supersession.draft_id!=latest["draft_id"] or not validate_lifecycle_chain(old+(supersession,)):raise DraftBoundaryRejected("prior draft supersession is required")
            c.execute(text("INSERT INTO governed_llm_drafts(draft_id,draft_stream_id,version,predecessor,invocation_id,request_id,correlation_id,tenant_id,output_classification,review_status,reviewable_content_hash,integrity_hash,issued_at,policy_version,payload,schema_version) VALUES(:id,:stream,:version,:predecessor,:invocation,:request,:correlation,:tenant,:classification,:review,:content_hash,:integrity,:issued,:policy,CAST(:payload AS jsonb),:schema)"),{"id":v.draft_id,"stream":v.draft_stream_id,"version":v.version,"predecessor":v.predecessor,"invocation":v.invocation_id,"request":v.request_id,"correlation":v.correlation_id,"tenant":v.tenant_id,"classification":v.output_classification,"review":v.review_status.value,"content_hash":v.reviewable_content_hash,"integrity":v.integrity_hash,"issued":v.issued_at,"policy":v.policy_version,"payload":json.dumps(self._codec.encode(v),sort_keys=True,separators=(",",":")),"schema":self._codec.schema_version})
            self._insert_lifecycle(c,active)
            if supersession:self._insert_lifecycle(c,supersession)
    def append_lifecycle(self,event):
        if event.tenant_id!=current_tenant_context().tenant_id:raise DraftBoundaryRejected("lifecycle tenant mismatch")
        with self._engine.begin() as c:
            c.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),{"key":"governed_llm_draft_lifecycle:"+event.draft_id})
            draft=c.execute(text("SELECT version FROM governed_llm_drafts WHERE draft_id=:id"),{"id":event.draft_id}).scalar_one_or_none()
            if draft!=event.draft_version:raise DraftBoundaryRejected("canonical draft and exact version are required")
            history=self._lifecycle_history(c,event.draft_id)
            if not validate_lifecycle_chain(history+(event,)):raise DraftBoundaryRejected("invalid lifecycle chain")
            self._insert_lifecycle(c,event)
    def get(self,draft_id):
        with self._engine.connect() as c:payload=c.execute(text("SELECT payload FROM governed_llm_drafts WHERE draft_id=:id"),{"id":draft_id}).scalar_one_or_none()
        return self._decode(payload)
    def history(self,stream_id):
        with self._engine.connect() as c:values=c.execute(text("SELECT payload FROM governed_llm_drafts WHERE draft_stream_id=:s ORDER BY version"),{"s":stream_id}).scalars().all()
        return tuple(self._decode(x) for x in values)
    def latest(self,stream_id):
        values=self.history(stream_id);return values[-1] if values else None
    def lifecycle_history(self,draft_id):
        with self._engine.connect() as c:return self._lifecycle_history(c,draft_id)
    def current_status(self,draft_id,version):
        draft=self.get(draft_id)
        if draft is None or draft.version!=version:return None
        history=self.lifecycle_history(draft_id)
        if not validate_lifecycle_chain(history):raise DraftBoundaryRejected("invalid lifecycle chain")
        return history[-1].resulting_status if history else None
    def current_active(self,stream_id):
        for draft in reversed(self.history(stream_id)):
            if self.current_status(draft.draft_id,draft.version) is GovernedLLMDraftLifecycleStatus.ACTIVE:return draft
        return None
    def _insert_lifecycle(self,c,event):
        c.execute(text("INSERT INTO governed_llm_draft_lifecycle_events(lifecycle_event_id,draft_id,draft_version,tenant_id,stream_position,prior_status,resulting_status,reason_reference,actor_reference,policy_version,occurred_at,predecessor_event_id,previous_hash,integrity_hash,payload,schema_version) VALUES(:id,:draft,:version,:tenant,:position,:prior,:result,:reason,:actor,:policy,:at,:predecessor,:previous_hash,:integrity,CAST(:payload AS jsonb),:schema)"),{"id":event.lifecycle_event_id,"draft":event.draft_id,"version":event.draft_version,"tenant":event.tenant_id,"position":event.stream_position,"prior":event.prior_status.value if event.prior_status else None,"result":event.resulting_status.value,"reason":event.reason_reference,"actor":event.actor_reference,"policy":event.policy_version,"at":event.occurred_at,"predecessor":event.predecessor_event_id,"previous_hash":event.previous_hash,"integrity":event.integrity_hash,"payload":json.dumps(self._codec.encode(event),sort_keys=True,separators=(",",":")),"schema":self._codec.schema_version})
    def _lifecycle_history(self,c,draft_id):
        values=c.execute(text("SELECT payload FROM governed_llm_draft_lifecycle_events WHERE draft_id=:id ORDER BY stream_position"),{"id":draft_id}).scalars().all()
        return tuple(self._codec.decode(x) for x in values)
    def _decode(self,payload):
        if payload is None:return None
        value=self._codec.decode(payload)
        if not validate_draft_integrity(value,self._attestor):raise DraftBoundaryRejected("persisted draft integrity is invalid")
        if value.tenant_id!=current_tenant_context().tenant_id:raise DraftBoundaryRejected("draft tenant mismatch")
        return value
