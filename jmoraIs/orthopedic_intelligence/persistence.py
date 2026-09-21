from __future__ import annotations
import json
from hashlib import sha256
from uuid import uuid4
from dataclasses import fields,is_dataclass
from datetime import datetime
from enum import Enum
from sqlalchemy import text
from jmoraIs.tenancy.context import current_tenant_context
from jmoraIs.reasoning_input.persistence import ReasoningInputJsonCodec
from . import domain
from .domain import *
_TYPES={n:v for n,v in vars(domain).items() if isinstance(v,type) and is_dataclass(v)}
_ENUMS={n:v for n,v in vars(domain).items() if isinstance(v,type) and issubclass(v,Enum)}
class OrthopedicJsonCodec:
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
        if "__type__" in v:
            kind=_TYPES.get(v["__type__"])
            if kind is None:return ReasoningInputJsonCodec().decode(v)
            return kind(**{k:self.decode(x) for k,x in v.items() if k!="__type__"})
        return {k:self.decode(x) for k,x in v.items()}
class PostgreSQLOrthopedicAssessmentRepository:
    def __init__(self,engine,codec=None,*,reasoning_inputs=None):self._engine=engine;self._codec=codec or OrthopedicJsonCodec();self._reasoning_inputs=reasoning_inputs
    def append(self,v):
        with self._engine.begin() as c:
            c.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),{"key":"orthopedic:"+v.subject_reference})
            latest=c.execute(text("SELECT set_id,set_version FROM orthopedic_assessment_versions WHERE subject_reference=:s ORDER BY set_version DESC LIMIT 1"),{"s":v.subject_reference}).mappings().first()
            if latest and (v.previous_set_id!=latest["set_id"] or v.set_version!=latest["set_version"]+1):raise OrthopedicVersionConflict("invalid assessment version chain")
            if not latest and (v.set_version!=1 or v.previous_set_id is not None):raise OrthopedicVersionConflict("assessment history must begin at version 1")
            c.execute(text("INSERT INTO orthopedic_assessment_versions(set_id,subject_reference,set_version,previous_set_id,assessment_id,review_status,generated_at,reasoning_input_reference_id,reasoning_lineage_status,payload,schema_version) VALUES(:id,:s,:v,:p,:a,:r,:at,:reasoning,:lineage,CAST(:payload AS jsonb),:schema)"),{"id":v.set_id,"s":v.subject_reference,"v":v.set_version,"p":v.previous_set_id,"a":v.assessment.assessment_id,"r":v.review_status.value,"at":v.generated_at,"reasoning":v.clinical_reasoning_input_reference.reference_id if v.clinical_reasoning_input_reference else None,"lineage":v.reasoning_lineage_status,"payload":json.dumps(self._codec.encode(v),sort_keys=True,separators=(",",":")),"schema":self._codec.schema_version})
    def history(self,s):
        with self._engine.connect() as c:rows=c.execute(text("SELECT payload FROM orthopedic_assessment_versions WHERE subject_reference=:s ORDER BY set_version"),{"s":s}).scalars().all()
        return tuple(self._codec.decode(x) for x in rows)
    def latest(self,s):
        values=self.history(s);return values[-1] if values else None
    def reference_for(self,value):
        if not isinstance(value,OrthopedicAssessmentSet):raise OrthopedicBoundaryError("persisted OrthopedicAssessmentSet is required")
        tenant=current_tenant_context().tenant_id;history=self.history(value.subject_reference);_validate_chain(history,value.subject_reference)
        matches=tuple(item for item in history if item.set_id==value.set_id and item.set_version==value.set_version)
        if len(matches)!=1 or matches[0]!=value:raise OrthopedicBoundaryError("assessment set does not match canonical persistence")
        reference=PersistedOrthopedicAssessmentSetReference("osr_"+uuid4().hex,value.set_id,value.set_version,value.subject_reference,tenant,value.assessment.policy_version,_set_integrity(self._codec,value),value.generated_at)
        with self._engine.begin() as c:
            c.execute(text("""INSERT INTO orthopedic_assessment_set_references(reference_id,tenant_id,set_id,set_version,subject_reference,policy_version,integrity_hash,issued_at)
              VALUES(:reference,:tenant,:set_id,:version,:subject,:policy,:integrity,:issued)"""),{"reference":reference.reference_id,"tenant":tenant,"set_id":reference.set_id,"version":reference.set_version,"subject":reference.subject_reference,"policy":reference.policy_version,"integrity":reference.integrity_hash,"issued":reference.issued_at})
        return reference
    def get_exact(self,reference):
        if not isinstance(reference,PersistedOrthopedicAssessmentSetReference):raise OrthopedicBoundaryError("owner-issued orthopedic-set reference is required")
        tenant=current_tenant_context().tenant_id
        if reference.tenant_id!=tenant:raise OrthopedicBoundaryError("orthopedic-set reference tenant mismatch")
        with self._engine.connect() as c:
            row=c.execute(text("SELECT * FROM orthopedic_assessment_set_references WHERE reference_id=:reference"),{"reference":reference.reference_id}).mappings().first()
            payload=c.execute(text("SELECT payload FROM orthopedic_assessment_versions WHERE set_id=:set_id AND set_version=:version AND subject_reference=:subject"),{"set_id":reference.set_id,"version":reference.set_version,"subject":reference.subject_reference}).scalar_one_or_none()
        if row is None or payload is None:raise OrthopedicBoundaryError("exact persisted orthopedic set is unavailable")
        actual=(row["reference_id"],row["set_id"],row["set_version"],row["subject_reference"],row["tenant_id"],row["policy_version"],row["integrity_hash"],row["issued_at"])
        expected=(reference.reference_id,reference.set_id,reference.set_version,reference.subject_reference,reference.tenant_id,reference.policy_version,reference.integrity_hash,reference.issued_at)
        if actual!=expected:raise OrthopedicBoundaryError("persisted orthopedic-set reference mismatch")
        value=self._codec.decode(payload);history=self.history(reference.subject_reference);_validate_chain(history,reference.subject_reference)
        if value.set_id!=reference.set_id or value.set_version!=reference.set_version or value.subject_reference!=reference.subject_reference:raise OrthopedicBoundaryError("orthopedic-set identity mismatch")
        if value.assessment.policy_version!=reference.policy_version or not value.assessment.provenance_references:raise OrthopedicBoundaryError("orthopedic-set governance mismatch")
        if _set_integrity(self._codec,value)!=reference.integrity_hash:raise OrthopedicBoundaryError("orthopedic-set integrity mismatch")
        if value.clinical_reasoning_input_reference is not None:
            if self._reasoning_inputs is None:raise OrthopedicBoundaryError("canonical Clinical Reasoning exact query port is required")
            exact=self._reasoning_inputs.get_exact(value.clinical_reasoning_input_reference)
            if (exact.input_id,exact.input_version)!=(value.assessment.reasoning_input_id,value.assessment.reasoning_input_version):raise OrthopedicBoundaryError("orthopedic Clinical Reasoning lineage mismatch")
        return value
def _set_integrity(codec,value):return sha256(json.dumps(codec.encode(value),sort_keys=True,separators=(",",":")).encode()).hexdigest()
def _validate_chain(history,subject):
    for index,item in enumerate(history,1):
        previous=None if index==1 else history[index-2].set_id
        if item.subject_reference!=subject or item.set_version!=index or item.previous_set_id!=previous:raise OrthopedicBoundaryError("persisted orthopedic-set version chain is invalid")
class PostgreSQLOrthopedicAuditAdapter:
    def __init__(self,engine):self._engine=engine
    def append(self,e):
        with self._engine.begin() as c:c.execute(text("INSERT INTO orthopedic_assessment_audit(event_id,subject_reference,set_id,event_type,occurred_at,actor_id,decision_code,reference_ids,policy_version) VALUES(:id,:s,:set,:type,:at,:actor,:decision,CAST(:refs AS jsonb),:policy)"),{"id":e.event_id,"s":e.subject_reference,"set":e.set_id,"type":e.event_type.value,"at":e.occurred_at,"actor":e.actor_id,"decision":e.decision_code,"refs":json.dumps(e.reference_ids),"policy":e.policy_version})
    def history(self,s):
        with self._engine.connect() as c:rows=c.execute(text("SELECT * FROM orthopedic_assessment_audit WHERE subject_reference=:s ORDER BY sequence_id"),{"s":s}).mappings().all()
        return tuple(OrthopedicAuditEvent(x["event_id"],x["subject_reference"],x["set_id"],OrthopedicAuditType(x["event_type"]),x["occurred_at"],x["actor_id"],x["decision_code"],tuple(x["reference_ids"]),x["policy_version"]) for x in rows)
