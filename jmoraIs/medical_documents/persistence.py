from __future__ import annotations
import json
from dataclasses import fields,is_dataclass
from datetime import date,datetime
from enum import Enum
from sqlalchemy import text
from . import domain
from .domain import *
from jmoraIs.guideline_engine.domain import PersistedGuidelineRecommendationSetReference
from jmoraIs.orthopedic_intelligence.domain import PersistedOrthopedicAssessmentSetReference
_TYPES={n:v for n,v in vars(domain).items() if isinstance(v,type) and is_dataclass(v)}
_TYPES["PersistedGuidelineRecommendationSetReference"]=PersistedGuidelineRecommendationSetReference
_TYPES["PersistedOrthopedicAssessmentSetReference"]=PersistedOrthopedicAssessmentSetReference
_ENUMS={n:v for n,v in vars(domain).items() if isinstance(v,type) and issubclass(v,Enum)}
class MedicalDocumentJsonCodec:
    schema_version=1
    def encode(self,v):
        if is_dataclass(v):return {"__type__":type(v).__name__,**{f.name:self.encode(getattr(v,f.name)) for f in fields(v)}}
        if isinstance(v,Enum):return {"__enum__":type(v).__name__,"value":v.value}
        if isinstance(v,datetime):return {"__datetime__":v.isoformat()}
        if isinstance(v,date):return {"__date__":v.isoformat()}
        if isinstance(v,tuple):return {"__tuple__":[self.encode(x) for x in v]}
        return v
    def decode(self,v):
        if isinstance(v,list):return tuple(self.decode(x) for x in v)
        if not isinstance(v,dict):return v
        if "__enum__" in v:return _ENUMS[v["__enum__"]](v["value"])
        if "__datetime__" in v:return datetime.fromisoformat(v["__datetime__"])
        if "__date__" in v:return date.fromisoformat(v["__date__"])
        if "__tuple__" in v:return tuple(self.decode(x) for x in v["__tuple__"])
        if "__type__" in v:return _TYPES[v["__type__"]](**{k:self.decode(x) for k,x in v.items() if k!="__type__"})
        return {k:self.decode(x) for k,x in v.items()}
class PostgreSQLMedicalDocumentRepository:
    def __init__(self,engine,codec=None):self._engine=engine;self._codec=codec or MedicalDocumentJsonCodec()
    def append(self,v):
        reference=v.document.guideline_recommendation_set_reference
        orthopedic_reference=v.document.orthopedic_assessment_set_reference
        with self._engine.begin() as c:
            c.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),{"key":"medical_document:"+v.document_stream_id})
            latest=c.execute(text("SELECT version_id,version FROM medical_document_versions WHERE document_stream_id=:s ORDER BY version DESC LIMIT 1"),{"s":v.document_stream_id}).mappings().first()
            if latest and (v.previous_version_id!=latest["version_id"] or v.version!=latest["version"]+1):raise DocumentVersionConflict("invalid document version chain")
            if not latest and (v.version!=1 or v.previous_version_id is not None):raise DocumentVersionConflict("document history must begin at version 1")
            c.execute(text("INSERT INTO medical_document_versions(version_id,document_stream_id,version,previous_version_id,document_id,document_type,status,review_status,template_version,created_at,guideline_set_reference_id,guideline_set_id,guideline_set_version,orthopedic_set_reference_id,orthopedic_set_id,orthopedic_set_version,payload,schema_version) VALUES(:id,:s,:v,:p,:doc,:type,:status,:review,:template,:at,:guideline_reference,:guideline_set,:guideline_version,:orthopedic_reference,:orthopedic_set,:orthopedic_version,CAST(:payload AS jsonb),:schema)"),{"id":v.version_id,"s":v.document_stream_id,"v":v.version,"p":v.previous_version_id,"doc":v.document.document_id,"type":v.document.document_type.value,"status":v.document.status.value,"review":v.document.review_status.value,"template":v.document.template_version,"at":v.created_at,"guideline_reference":reference.reference_id if reference else None,"guideline_set":reference.set_id if reference else None,"guideline_version":reference.set_version if reference else None,"orthopedic_reference":orthopedic_reference.reference_id if orthopedic_reference else None,"orthopedic_set":orthopedic_reference.set_id if orthopedic_reference else None,"orthopedic_version":orthopedic_reference.set_version if orthopedic_reference else None,"payload":json.dumps(self._codec.encode(v),sort_keys=True,separators=(",",":")),"schema":self._codec.schema_version})
    def history(self,s):
        with self._engine.connect() as c:rows=c.execute(text("SELECT payload,guideline_set_reference_id,guideline_set_id,guideline_set_version,orthopedic_set_reference_id,orthopedic_set_id,orthopedic_set_version FROM medical_document_versions WHERE document_stream_id=:s ORDER BY version"),{"s":s}).mappings().all()
        values=[]
        for row in rows:
            value=self._codec.decode(row["payload"]);reference=value.document.guideline_recommendation_set_reference
            expected=(reference.reference_id,reference.set_id,reference.set_version) if reference else (None,None,None)
            if (row["guideline_set_reference_id"],row["guideline_set_id"],row["guideline_set_version"])!=expected:raise DocumentBoundaryRejected("guideline-set lineage integrity mismatch")
            orthopedic=value.document.orthopedic_assessment_set_reference
            orthopedic_expected=(orthopedic.reference_id,orthopedic.set_id,orthopedic.set_version) if orthopedic else (None,None,None)
            if (row["orthopedic_set_reference_id"],row["orthopedic_set_id"],row["orthopedic_set_version"])!=orthopedic_expected:raise DocumentBoundaryRejected("orthopedic-set lineage integrity mismatch")
            values.append(value)
        return tuple(values)
    def latest(self,s):
        values=self.history(s);return values[-1] if values else None
class PostgreSQLDocumentAuditAdapter:
    def __init__(self,engine):self._engine=engine
    def append(self,e):
        with self._engine.begin() as c:c.execute(text("INSERT INTO medical_document_audit(event_id,document_stream_id,version_id,event_type,occurred_at,actor_id,decision_code,reference_ids,policy_version) VALUES(:id,:s,:v,:type,:at,:actor,:decision,CAST(:refs AS jsonb),:policy)"),{"id":e.event_id,"s":e.document_stream_id,"v":e.version_id,"type":e.event_type.value,"at":e.occurred_at,"actor":e.actor_id,"decision":e.decision_code,"refs":json.dumps(e.reference_ids),"policy":e.policy_version})
    def history(self,s):
        with self._engine.connect() as c:rows=c.execute(text("SELECT * FROM medical_document_audit WHERE document_stream_id=:s ORDER BY sequence_id"),{"s":s}).mappings().all()
        return tuple(DocumentAuditEvent(x["event_id"],x["document_stream_id"],x["version_id"],DocumentAuditType(x["event_type"]),x["occurred_at"],x["actor_id"],x["decision_code"],tuple(x["reference_ids"]),x["policy_version"]) for x in rows)
