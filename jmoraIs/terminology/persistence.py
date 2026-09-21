from __future__ import annotations
import json
from dataclasses import fields,is_dataclass
from datetime import date,datetime
from decimal import Decimal
from enum import Enum
from sqlalchemy import text
from . import domain
from .domain import *
_TYPES={name:value for name,value in vars(domain).items() if isinstance(value,type) and is_dataclass(value)}
_ENUMS={name:value for name,value in vars(domain).items() if isinstance(value,type) and issubclass(value,Enum)}
class TerminologyJsonCodec:
    schema_version=1
    def encode(self,value):
        if is_dataclass(value):return {"__type__":type(value).__name__,**{item.name:self.encode(getattr(value,item.name)) for item in fields(value)}}
        if isinstance(value,Enum):return {"__enum__":type(value).__name__,"value":value.value}
        if isinstance(value,datetime):return {"__datetime__":value.isoformat()}
        if isinstance(value,date):return {"__date__":value.isoformat()}
        if isinstance(value,Decimal):return {"__decimal__":str(value)}
        if isinstance(value,tuple):return {"__tuple__":[self.encode(item) for item in value]}
        return value
    def decode(self,value):
        if isinstance(value,list):return tuple(self.decode(item) for item in value)
        if not isinstance(value,dict):return value
        if "__enum__" in value:return _ENUMS[value["__enum__"]](value["value"])
        if "__datetime__" in value:return datetime.fromisoformat(value["__datetime__"])
        if "__date__" in value:return date.fromisoformat(value["__date__"])
        if "__decimal__" in value:return Decimal(value["__decimal__"])
        if "__tuple__" in value:return tuple(self.decode(item) for item in value["__tuple__"])
        if "__type__" in value:
            kind=_TYPES.get(value["__type__"])
            if kind is None:raise InvalidTerminologyRecord("unknown terminology document type")
            return kind(**{key:self.decode(item) for key,item in value.items() if key!="__type__"})
        return {key:self.decode(item) for key,item in value.items()}
class PostgreSQLTerminologyRepository:
    def __init__(self,engine,codec=None):self._engine=engine;self._codec=codec or TerminologyJsonCodec()
    def append(self,stream_id,record):
        with self._engine.begin() as connection:
            connection.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),{"key":"terminology:"+stream_id})
            position=connection.execute(text("SELECT COALESCE(MAX(stream_position),0)+1 FROM terminology_records WHERE stream_id=:stream"),{"stream":stream_id}).scalar_one()
            connection.execute(text("""INSERT INTO terminology_records(stream_id,stream_position,record_type,code_system,terminology_version,payload,schema_version)
              VALUES(:stream,:position,:type,:system,:version,CAST(:payload AS jsonb),:schema)"""),{"stream":stream_id,"position":position,
              "type":type(record).__name__,"system":self._system(record),"version":self._version(record),
              "payload":json.dumps(self._codec.encode(record),sort_keys=True,separators=(",",":")),"schema":self._codec.schema_version})
    def history(self,stream_id):
        with self._engine.connect() as connection:payloads=connection.execute(text("SELECT payload FROM terminology_records WHERE stream_id=:stream ORDER BY stream_position"),{"stream":stream_id}).scalars().all()
        return tuple(self._codec.decode(item) for item in payloads)
    def latest(self,stream_id):
        history=self.history(stream_id);return history[-1] if history else None
    def _latest_records(self,record_type=None):
        query="""SELECT DISTINCT ON (stream_id) payload FROM terminology_records {where} ORDER BY stream_id,stream_position DESC""".format(where="WHERE record_type=:type" if record_type else "")
        with self._engine.connect() as connection:payloads=connection.execute(text(query),{"type":record_type} if record_type else {}).scalars().all()
        return tuple(self._codec.decode(item) for item in payloads)
    def search(self,term,code_system,version):
        key=term.casefold().strip();found=[]
        for item in self._latest_records("ClinicalConcept"):
            terms={item.preferred_term.casefold(),item.display_name.casefold(),*(value.casefold() for value in item.synonyms),*(code.code.casefold() for code in item.codes)}
            if item.code_system is code_system and item.version==version and key in terms:found.append(item)
        return tuple(sorted(found,key=lambda item:item.canonical_id))
    def mappings(self,source_codes,target_system):
        source={(item.code_system,item.code,item.version) for item in source_codes};found=[]
        for item in self._latest_records("ConceptMapping"):
            if source=={(code.code_system,code.code,code.version) for code in item.source_codes} and any(code.code_system is target_system for code in item.target_codes):found.append(item)
        return tuple(sorted(found,key=lambda item:item.mapping_id))
    def version(self,code_system,version):return next((item for item in self._latest_records("TerminologyVersion") if item.code_system is code_system and item.version==version),None)
    @staticmethod
    def _system(record):
        if hasattr(record,"code_system"):return record.code_system.value
        if isinstance(record,ConceptMapping):return record.source_codes[0].code_system.value
        return "RELATIONSHIP"
    @staticmethod
    def _version(record):
        if hasattr(record,"version"):return record.version
        if isinstance(record,ConceptMapping):return record.source_codes[0].version
        return "UNKNOWN"
class PostgreSQLTerminologyAuditAdapter:
    def __init__(self,engine):self._engine=engine
    def append(self,event):
        with self._engine.begin() as connection:connection.execute(text("""INSERT INTO terminology_audit_events
          (event_id,event_type,subject_reference,occurred_at,actor_id,version_reference,outcome,provenance)
          VALUES(:id,:type,:subject,:at,:actor,:version,:outcome,:provenance)"""),{"id":event.event_id,"type":event.event_type.value,
          "subject":event.subject_reference,"at":event.occurred_at,"actor":event.actor_id,"version":event.version_reference,"outcome":event.outcome,"provenance":event.provenance})
    def history(self,subject_reference):
        with self._engine.connect() as connection:rows=connection.execute(text("SELECT * FROM terminology_audit_events WHERE subject_reference=:subject ORDER BY sequence_id"),{"subject":subject_reference}).mappings().all()
        return tuple(TerminologyAuditEvent(row["event_id"],TerminologyAuditType(row["event_type"]),row["subject_reference"],row["occurred_at"],row["actor_id"],row["version_reference"],row["outcome"],row["provenance"]) for row in rows)
