from __future__ import annotations
import json
from dataclasses import fields,is_dataclass
from datetime import date,datetime
from enum import Enum
from sqlalchemy import text
from . import domain
from .domain import *
from jmoraIs.terminology.domain import MappingType,PersistedTerminologyMappingGovernanceReference
from jmoraIs.clinical_state.exact_reference import PersistedClinicalStateReference
from jmoraIs.appraisal.exact_reference import PersistedGovernedEvidenceReference
_TYPES={name:value for name,value in vars(domain).items() if isinstance(value,type) and is_dataclass(value)}
_TYPES["PersistedTerminologyMappingGovernanceReference"]=PersistedTerminologyMappingGovernanceReference
_TYPES["PersistedClinicalStateReference"]=PersistedClinicalStateReference
_TYPES["PersistedGovernedEvidenceReference"]=PersistedGovernedEvidenceReference
_ENUMS={name:value for name,value in vars(domain).items() if isinstance(value,type) and issubclass(value,Enum)}
_ENUMS["MappingType"]=MappingType
class ReasoningInputJsonCodec:
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
            if kind is None:raise InvalidReasoningInput("unknown reasoning-input document type")
            return kind(**{key:self.decode(item) for key,item in value.items() if key!="__type__"})
        return {key:self.decode(item) for key,item in value.items()}
class PostgreSQLClinicalReasoningInputRepository:
    def __init__(self,engine,codec=None):self._engine=engine;self._codec=codec or ReasoningInputJsonCodec()
    def append(self,value):
        with self._engine.begin() as connection:
            connection.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),{"key":"reasoning_input:"+value.subject_reference})
            latest=connection.execute(text("SELECT input_id,input_version FROM clinical_reasoning_input_versions WHERE subject_reference=:subject ORDER BY input_version DESC LIMIT 1"),{"subject":value.subject_reference}).mappings().first()
            if latest and (value.previous_input_id!=latest["input_id"] or value.input_version!=latest["input_version"]+1):raise ReasoningInputVersionConflict("invalid reasoning-input version chain")
            if not latest and (value.input_version!=1 or value.previous_input_id is not None):raise ReasoningInputVersionConflict("reasoning-input history must begin at version 1")
            connection.execute(text("""INSERT INTO clinical_reasoning_input_versions
              (input_id,subject_reference,input_version,previous_input_id,created_at,review_status,readiness,terminology_governance_references,clinical_state_reference_id,governed_evidence_reference_ids,exact_upstream_lineage_status,payload,schema_version)
              VALUES(:id,:subject,:version,:previous,:created,:review,:readiness,CAST(:terminology_refs AS jsonb),:state_ref,CAST(:evidence_refs AS jsonb),:lineage,CAST(:payload AS jsonb),:schema)"""),
              {"id":value.input_id,"subject":value.subject_reference,"version":value.input_version,"previous":value.previous_input_id,"created":value.created_at,
               "review":value.review_status.value,"readiness":value.readiness.value,"terminology_refs":json.dumps([item.reference_id for item in value.terminology_governance_references]),"state_ref":value.clinical_state_reference.reference_id if value.clinical_state_reference else None,"evidence_refs":json.dumps([item.reference_id for item in value.governed_evidence_references]),"lineage":value.exact_upstream_lineage_status.value,"payload":json.dumps(self._codec.encode(value),sort_keys=True,separators=(",",":")),"schema":self._codec.schema_version})
    def get(self,input_id):
        with self._engine.connect() as connection:row=connection.execute(text("SELECT payload,terminology_governance_references,clinical_state_reference_id,governed_evidence_reference_ids,exact_upstream_lineage_status FROM clinical_reasoning_input_versions WHERE input_id=:id"),{"id":input_id}).mappings().first()
        if not row:return None
        value=self._codec.decode(row["payload"])
        if tuple(row["terminology_governance_references"])!=tuple(item.reference_id for item in value.terminology_governance_references):raise InvalidReasoningInput("terminology governance lineage integrity mismatch")
        if (row["clinical_state_reference_id"]!=(value.clinical_state_reference.reference_id if value.clinical_state_reference else None) or tuple(row["governed_evidence_reference_ids"])!=tuple(item.reference_id for item in value.governed_evidence_references) or row["exact_upstream_lineage_status"]!=value.exact_upstream_lineage_status.value):raise InvalidReasoningInput("exact upstream lineage integrity mismatch")
        return value
    def history(self,subject_reference):
        with self._engine.connect() as connection:rows=connection.execute(text("SELECT payload,terminology_governance_references,clinical_state_reference_id,governed_evidence_reference_ids,exact_upstream_lineage_status FROM clinical_reasoning_input_versions WHERE subject_reference=:subject ORDER BY input_version"),{"subject":subject_reference}).mappings().all()
        values=[]
        for row in rows:
            value=self._codec.decode(row["payload"])
            if tuple(row["terminology_governance_references"])!=tuple(item.reference_id for item in value.terminology_governance_references):raise InvalidReasoningInput("terminology governance lineage integrity mismatch")
            if (row["clinical_state_reference_id"]!=(value.clinical_state_reference.reference_id if value.clinical_state_reference else None) or tuple(row["governed_evidence_reference_ids"])!=tuple(item.reference_id for item in value.governed_evidence_references) or row["exact_upstream_lineage_status"]!=value.exact_upstream_lineage_status.value):raise InvalidReasoningInput("exact upstream lineage integrity mismatch")
            values.append(value)
        return tuple(values)
    def latest(self,subject_reference):
        items=self.history(subject_reference);return items[-1] if items else None
class PostgreSQLReasoningInputAuditAdapter:
    def __init__(self,engine):self._engine=engine
    def append(self,event):
        with self._engine.begin() as connection:connection.execute(text("""INSERT INTO clinical_reasoning_input_audit
          (event_id,subject_reference,input_id,event_type,occurred_at,actor_id,source_reference,policy_version,decision_code)
          VALUES(:id,:subject,:input,:type,:at,:actor,:source,:policy,:decision)"""),{"id":event.event_id,"subject":event.subject_reference,
          "input":event.input_id,"type":event.event_type.value,"at":event.occurred_at,"actor":event.actor_id,"source":event.source_reference,
          "policy":event.policy_version,"decision":event.decision_code})
    def history(self,subject_reference):
        with self._engine.connect() as connection:rows=connection.execute(text("SELECT * FROM clinical_reasoning_input_audit WHERE subject_reference=:subject ORDER BY sequence_id"),{"subject":subject_reference}).mappings().all()
        return tuple(ReasoningInputAuditEvent(row["event_id"],row["subject_reference"],row["input_id"],ReasoningAuditType(row["event_type"]),row["occurred_at"],row["actor_id"],row["source_reference"],row["policy_version"],row["decision_code"]) for row in rows)
