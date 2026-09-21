from __future__ import annotations
import json
from hashlib import sha256
from uuid import uuid4
from dataclasses import fields,is_dataclass
from datetime import date,datetime
from enum import Enum
from sqlalchemy import text
from jmoraIs.tenancy.context import current_tenant_context
from . import domain
from .domain import *
_TYPES={name:value for name,value in vars(domain).items() if isinstance(value,type) and is_dataclass(value)}
_ENUMS={name:value for name,value in vars(domain).items() if isinstance(value,type) and issubclass(value,Enum)}
class GuidelineRecommendationJsonCodec:
    schema_version=1
    def encode(self,value):
        if is_dataclass(value):return {"__type__":type(value).__name__,**{item.name:self.encode(getattr(value,item.name)) for item in fields(value)}}
        if isinstance(value,Enum):return {"__enum__":type(value).__name__,"value":value.value}
        if isinstance(value,datetime):return {"__datetime__":value.isoformat()}
        if isinstance(value,date):return {"__date__":value.isoformat()}
        if isinstance(value,tuple):return {"__tuple__":[self.encode(item) for item in value]}
        return value
    def decode(self,value):
        if isinstance(value,list):return tuple(self.decode(item) for item in value)
        if not isinstance(value,dict):return value
        if "__enum__" in value:return _ENUMS[value["__enum__"]](value["value"])
        if "__datetime__" in value:return datetime.fromisoformat(value["__datetime__"])
        if "__date__" in value:return date.fromisoformat(value["__date__"])
        if "__tuple__" in value:return tuple(self.decode(item) for item in value["__tuple__"])
        if "__type__" in value:
            kind=_TYPES.get(value["__type__"])
            if kind is None:raise GuidelineBoundaryRejected("unknown recommendation document type")
            return kind(**{key:self.decode(item) for key,item in value.items() if key!="__type__"})
        return {key:self.decode(item) for key,item in value.items()}
class PostgreSQLRecommendationRepository:
    def __init__(self,engine,codec=None):self._engine=engine;self._codec=codec or GuidelineRecommendationJsonCodec()
    def append(self,value):
        with self._engine.begin() as connection:
            connection.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),{"key":"guideline_recommendation:"+value.subject_reference})
            latest=connection.execute(text("SELECT set_id,set_version FROM guideline_recommendation_versions WHERE subject_reference=:subject ORDER BY set_version DESC LIMIT 1"),{"subject":value.subject_reference}).mappings().first()
            if latest and (value.previous_set_id!=latest["set_id"] or value.set_version!=latest["set_version"]+1):raise RecommendationVersionConflict("invalid recommendation version chain")
            if not latest and (value.set_version!=1 or value.previous_set_id is not None):raise RecommendationVersionConflict("recommendation history must begin at version 1")
            connection.execute(text("""INSERT INTO guideline_recommendation_versions(set_id,subject_reference,set_version,previous_set_id,reasoning_input_id,readiness,review_status,policy_version,generated_at,payload,schema_version)
              VALUES(:id,:subject,:version,:previous,:input,:readiness,:review,:policy,:at,CAST(:payload AS jsonb),:schema)"""),{"id":value.set_id,"subject":value.subject_reference,"version":value.set_version,"previous":value.previous_set_id,"input":value.reasoning_input_id,"readiness":value.readiness.value,"review":value.review_status.value,"policy":value.policy_version,"at":value.generated_at,"payload":json.dumps(self._codec.encode(value),sort_keys=True,separators=(",",":")),"schema":self._codec.schema_version})
    def history(self,subject_reference):
        with self._engine.connect() as connection:payloads=connection.execute(text("SELECT payload FROM guideline_recommendation_versions WHERE subject_reference=:subject ORDER BY set_version"),{"subject":subject_reference}).scalars().all()
        return tuple(self._codec.decode(item) for item in payloads)
    def latest(self,subject_reference):
        values=self.history(subject_reference);return values[-1] if values else None
    def reference_for(self,value):
        if not isinstance(value,GuidelineRecommendationSet):raise GuidelineBoundaryRejected("persisted GuidelineRecommendationSet is required")
        tenant=current_tenant_context().tenant_id
        history=self.history(value.subject_reference);_validate_chain(history,value.subject_reference)
        matches=tuple(item for item in history if item.set_id==value.set_id and item.set_version==value.set_version)
        if len(matches)!=1 or matches[0]!=value:raise GuidelineBoundaryRejected("recommendation set does not match canonical persistence")
        integrity=_set_integrity(self._codec,value)
        reference=PersistedGuidelineRecommendationSetReference("gsr_"+uuid4().hex,value.set_id,value.set_version,value.subject_reference,tenant,value.policy_version,integrity,value.generated_at)
        with self._engine.begin() as connection:
            connection.execute(text("""INSERT INTO guideline_recommendation_set_references
              (reference_id,tenant_id,set_id,set_version,subject_reference,policy_version,integrity_hash,issued_at)
              VALUES(:reference,:tenant,:set_id,:version,:subject,:policy,:integrity,:issued)"""),
              {"reference":reference.reference_id,"tenant":tenant,"set_id":reference.set_id,"version":reference.set_version,
               "subject":reference.subject_reference,"policy":reference.policy_version,"integrity":reference.integrity_hash,"issued":reference.issued_at})
        return reference
    def get_exact(self,reference):
        if not isinstance(reference,PersistedGuidelineRecommendationSetReference):raise GuidelineBoundaryRejected("owner-issued guideline-set reference is required")
        tenant=current_tenant_context().tenant_id
        if reference.tenant_id!=tenant:raise GuidelineBoundaryRejected("guideline-set reference tenant mismatch")
        with self._engine.connect() as connection:
            row=connection.execute(text("SELECT * FROM guideline_recommendation_set_references WHERE reference_id=:reference"),{"reference":reference.reference_id}).mappings().first()
            payload=connection.execute(text("""SELECT payload FROM guideline_recommendation_versions
              WHERE set_id=:set_id AND set_version=:version AND subject_reference=:subject"""),
              {"set_id":reference.set_id,"version":reference.set_version,"subject":reference.subject_reference}).scalar_one_or_none()
        if row is None or payload is None:raise GuidelineBoundaryRejected("exact persisted guideline set is unavailable")
        actual=(row["reference_id"],row["set_id"],row["set_version"],row["subject_reference"],row["tenant_id"],row["policy_version"],row["integrity_hash"],row["issued_at"])
        expected=(reference.reference_id,reference.set_id,reference.set_version,reference.subject_reference,reference.tenant_id,reference.policy_version,reference.integrity_hash,reference.issued_at)
        if actual!=expected:raise GuidelineBoundaryRejected("persisted guideline-set reference mismatch")
        value=self._codec.decode(payload);history=self.history(reference.subject_reference);_validate_chain(history,reference.subject_reference)
        if value.set_id!=reference.set_id or value.set_version!=reference.set_version or value.subject_reference!=reference.subject_reference:raise GuidelineBoundaryRejected("guideline-set identity mismatch")
        if value.policy_version!=reference.policy_version:raise GuidelineBoundaryRejected("guideline-set policy mismatch")
        if not value.provenance_references:raise GuidelineBoundaryRejected("guideline-set provenance is required")
        if _set_integrity(self._codec,value)!=reference.integrity_hash:raise GuidelineBoundaryRejected("guideline-set integrity mismatch")
        return value

def _set_integrity(codec,value):
    return sha256(json.dumps(codec.encode(value),sort_keys=True,separators=(",",":")).encode()).hexdigest()
def _validate_chain(history,subject):
    for index,item in enumerate(history,1):
        previous=None if index==1 else history[index-2].set_id
        if item.subject_reference!=subject or item.set_version!=index or item.previous_set_id!=previous:
            raise GuidelineBoundaryRejected("persisted guideline-set version chain is invalid")
class PostgreSQLRecommendationAuditAdapter:
    def __init__(self,engine):self._engine=engine
    def append(self,event):
        with self._engine.begin() as connection:connection.execute(text("""INSERT INTO guideline_recommendation_audit(event_id,subject_reference,set_id,event_type,occurred_at,actor_id,decision_code,reference_ids,policy_version)
          VALUES(:id,:subject,:set,:type,:at,:actor,:decision,CAST(:refs AS jsonb),:policy)"""),{"id":event.event_id,"subject":event.subject_reference,"set":event.set_id,"type":event.event_type.value,"at":event.occurred_at,"actor":event.actor_id,"decision":event.decision_code,"refs":json.dumps(event.reference_ids),"policy":event.policy_version})
    def history(self,subject_reference):
        with self._engine.connect() as connection:rows=connection.execute(text("SELECT * FROM guideline_recommendation_audit WHERE subject_reference=:subject ORDER BY sequence_id"),{"subject":subject_reference}).mappings().all()
        return tuple(RecommendationAuditEvent(row["event_id"],row["subject_reference"],row["set_id"],RecommendationAuditType(row["event_type"]),row["occurred_at"],row["actor_id"],row["decision_code"],tuple(row["reference_ids"]),row["policy_version"]) for row in rows)
