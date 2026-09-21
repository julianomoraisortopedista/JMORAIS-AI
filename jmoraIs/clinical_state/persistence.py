from __future__ import annotations
import json
from dataclasses import fields,is_dataclass
from datetime import datetime
from enum import Enum
from sqlalchemy import text
from . import domain
from .domain import *

_TYPES={name:value for name,value in vars(domain).items() if isinstance(value,type) and is_dataclass(value)}
_ENUMS={name:value for name,value in vars(domain).items() if isinstance(value,type) and issubclass(value,Enum)}
class ClinicalStateJsonCodec:
    schema_version=1
    def encode(self,value):
        if is_dataclass(value):return {"__type__":type(value).__name__,**{item.name:self.encode(getattr(value,item.name)) for item in fields(value)}}
        if isinstance(value,Enum):return {"__enum__":type(value).__name__,"value":value.value}
        if isinstance(value,datetime):return {"__datetime__":value.isoformat()}
        if isinstance(value,tuple):return {"__tuple__":[self.encode(item) for item in value]}
        return value
    def decode(self,value):
        if isinstance(value,list):return tuple(self.decode(item) for item in value)
        if not isinstance(value,dict):return value
        if "__enum__" in value:return _ENUMS[value["__enum__"]](value["value"])
        if "__datetime__" in value:return datetime.fromisoformat(value["__datetime__"])
        if "__tuple__" in value:return tuple(self.decode(item) for item in value["__tuple__"])
        if "__type__" in value:
            kind=_TYPES.get(value["__type__"])
            if kind is None:raise ClinicalStateError("unknown clinical-state document type")
            return kind(**{key:self.decode(item) for key,item in value.items() if key!="__type__"})
        return {key:self.decode(item) for key,item in value.items()}

class PostgreSQLClinicalStateRepository:
    def __init__(self,engine,codec=None):
        if engine.dialect.name!="postgresql":raise ValueError("clinical state adapter requires PostgreSQL")
        self._engine=engine;self._codec=codec or ClinicalStateJsonCodec()
    def append(self,state):
        with self._engine.begin() as connection:
            connection.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),{"key":"clinical_state:"+state.pseudonymous_patient_id})
            latest=connection.execute(text("SELECT state_id,state_version FROM patient_clinical_state_versions WHERE patient_id=:patient ORDER BY state_version DESC LIMIT 1"),{"patient":state.pseudonymous_patient_id}).mappings().first()
            if latest and (state.previous_state_id!=latest["state_id"] or state.state_version!=latest["state_version"]+1):raise ClinicalStateVersionConflict("invalid state version chain")
            if not latest and (state.state_version!=1 or state.previous_state_id is not None):raise ClinicalStateVersionConflict("state history must begin at version 1")
            connection.execute(text("""INSERT INTO patient_clinical_state_versions
              (state_id,patient_id,patient_context_id,patient_context_version,state_version,previous_state_id,as_of,review_status,payload,schema_version)
              VALUES(:state,:patient,:context,:context_version,:version,:previous,:as_of,:review,CAST(:payload AS jsonb),:schema)"""),
              {"state":state.state_id,"patient":state.pseudonymous_patient_id,"context":state.patient_context_id,
               "context_version":state.patient_context_version,"version":state.state_version,"previous":state.previous_state_id,
               "as_of":state.as_of,"review":state.review_status.value,"payload":json.dumps(self._codec.encode(state),separators=(",",":"),sort_keys=True),"schema":self._codec.schema_version})
    def get(self,state_id):
        with self._engine.connect() as connection:payload=connection.execute(text("SELECT payload FROM patient_clinical_state_versions WHERE state_id=:state"),{"state":state_id}).scalar_one_or_none()
        return self._codec.decode(payload) if payload else None
    def history(self,patient_id):
        with self._engine.connect() as connection:payloads=connection.execute(text("SELECT payload FROM patient_clinical_state_versions WHERE patient_id=:patient ORDER BY state_version"),{"patient":patient_id}).scalars().all()
        return tuple(self._codec.decode(item) for item in payloads)
    def latest(self,patient_id):
        items=self.history(patient_id);return items[-1] if items else None
    def at(self,patient_id,as_of):
        items=tuple(item for item in self.history(patient_id) if item.as_of<=as_of);return items[-1] if items else None

class PostgreSQLClinicalStateAuditAdapter:
    def __init__(self,engine):self._engine=engine
    def append(self,event):
        with self._engine.begin() as connection:connection.execute(text("""INSERT INTO clinical_state_audit_events
          (event_id,patient_id,state_id,event_type,occurred_at,actor_id,source_event_id,provenance,detail_code)
          VALUES(:id,:patient,:state,:type,:at,:actor,:source,:provenance,:detail)"""),
          {"id":event.event_id,"patient":event.patient_id,"state":event.state_id,"type":event.event_type.value,"at":event.occurred_at,
           "actor":event.actor_id,"source":event.source_event_id,"provenance":event.provenance,"detail":event.detail_code})
    def history(self,patient_id):
        with self._engine.connect() as connection:rows=connection.execute(text("SELECT * FROM clinical_state_audit_events WHERE patient_id=:patient ORDER BY sequence_id"),{"patient":patient_id}).mappings().all()
        return tuple(ClinicalStateAuditEvent(row["event_id"],row["patient_id"],row["state_id"],ClinicalStateAuditType(row["event_type"]),row["occurred_at"],row["actor_id"],row["source_event_id"],row["provenance"],row["detail_code"]) for row in rows)
