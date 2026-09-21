from __future__ import annotations

import json
from uuid import uuid4
from dataclasses import asdict
from datetime import datetime
from enum import Enum
from sqlalchemy import text

from .domain import *
from .governance import mapping_governance_integrity_hash


class PostgreSQLTerminologyMappingGovernanceRepository:
    CLASSIFICATION="SHARED_GLOBAL_REFERENCE"
    def __init__(self,engine):self._engine=engine
    def append(self,value):
        if value.integrity_hash!=mapping_governance_integrity_hash(value):raise InvalidTerminologyRecord("mapping governance integrity is invalid")
        stream=value.target_concept_id or "unmapped:"+value.source_reference
        previous=self.current_by_concept(stream)
        if (previous is None and (value.version!=1 or value.predecessor_record_id is not None)) or (previous and (value.version!=previous.version+1 or value.predecessor_record_id!=previous.governance_record_id)):raise TerminologyVersionConflict("invalid mapping governance predecessor")
        with self._engine.begin() as connection:connection.execute(text("""INSERT INTO terminology_mapping_governance_versions
          (governance_record_id,mapping_stream_id,source_reference,target_concept_id,terminology_version,mapping_type,mapping_confidence,review_status,review_required,policy_version,created_at,version,predecessor_record_id,integrity_hash,payload)
          VALUES(:id,:stream,:source,:target,:term_version,:mapping_type,:confidence,:review_status,:review_required,:policy,:created,:version,:predecessor,:integrity,CAST(:payload AS jsonb))"""),
          {"id":value.governance_record_id,"stream":stream,"source":value.source_reference,"target":value.target_concept_id,
           "term_version":value.terminology_version,"mapping_type":value.mapping_type.value,"confidence":value.mapping_confidence.value,
           "review_status":value.review_status.value,"review_required":value.review_required,"policy":value.policy_version,
           "created":value.created_at,"version":value.version,"predecessor":value.predecessor_record_id,"integrity":value.integrity_hash,
           "payload":json.dumps(_encode(value),sort_keys=True,separators=(",",":"))})
    def get(self,identifier):
        with self._engine.connect() as connection:payload=connection.execute(text("SELECT payload FROM terminology_mapping_governance_versions WHERE governance_record_id=:id"),{"id":identifier}).scalar_one_or_none()
        return _decode(payload) if payload else None
    def current_by_concept(self,concept_id):
        with self._engine.connect() as connection:payload=connection.execute(text("SELECT payload FROM terminology_mapping_governance_versions WHERE mapping_stream_id=:id ORDER BY version DESC LIMIT 1"),{"id":concept_id}).scalar_one_or_none()
        return _decode(payload) if payload else None
    def history_by_concept(self,concept_id):
        with self._engine.connect() as connection:payloads=connection.execute(text("SELECT payload FROM terminology_mapping_governance_versions WHERE mapping_stream_id=:id ORDER BY version"),{"id":concept_id}).scalars().all()
        return tuple(_decode(item) for item in payloads)
    def by_source_reference(self,source_reference):
        with self._engine.connect() as connection:payloads=connection.execute(text("SELECT payload FROM terminology_mapping_governance_versions WHERE source_reference=:source ORDER BY created_at,version"),{"source":source_reference}).scalars().all()
        return tuple(_decode(item) for item in payloads)
    def reference_for(self,record):
        if not isinstance(record,TerminologyMappingGovernanceRecord):raise InvalidTerminologyRecord("persisted terminology governance record is required")
        persisted=self.get(record.governance_record_id)
        if persisted!=record or record.integrity_hash!=mapping_governance_integrity_hash(record):raise InvalidTerminologyRecord("terminology governance record does not match canonical persistence")
        _validate_governance_chain(self._engine,record)
        reference=PersistedTerminologyMappingGovernanceReference("tmr_"+uuid4().hex,record.governance_record_id,record.version,
          record.target_concept_id,record.terminology_version,record.source_reference,record.mapping_type,self.CLASSIFICATION,
          record.policy_version,record.integrity_hash,record.created_at)
        with self._engine.begin() as connection:connection.execute(text("""INSERT INTO terminology_mapping_governance_references
          (reference_id,governance_record_id,record_version,target_concept_id,terminology_version,source_reference,mapping_type,classification,policy_version,integrity_hash,issued_at)
          VALUES(:reference,:record,:version,:concept,:terminology,:source,:mapping,:classification,:policy,:integrity,:issued)"""),
          {"reference":reference.reference_id,"record":reference.governance_record_id,"version":reference.record_version,
           "concept":reference.target_concept_id,"terminology":reference.terminology_version,"source":reference.source_reference,
           "mapping":reference.mapping_type.value,"classification":reference.classification,"policy":reference.policy_version,
           "integrity":reference.integrity_hash,"issued":reference.issued_at})
        return reference
    def get_exact(self,reference):
        if not isinstance(reference,PersistedTerminologyMappingGovernanceReference):raise InvalidTerminologyRecord("owner-issued terminology governance reference is required")
        with self._engine.connect() as connection:row=connection.execute(text("SELECT * FROM terminology_mapping_governance_references WHERE reference_id=:reference"),{"reference":reference.reference_id}).mappings().first()
        if row is None:raise InvalidTerminologyRecord("persisted terminology governance reference is unavailable")
        actual=(row["reference_id"],row["governance_record_id"],row["record_version"],row["target_concept_id"],row["terminology_version"],row["source_reference"],MappingType(row["mapping_type"]),row["classification"],row["policy_version"],row["integrity_hash"],row["issued_at"])
        expected=(reference.reference_id,reference.governance_record_id,reference.record_version,reference.target_concept_id,reference.terminology_version,reference.source_reference,reference.mapping_type,reference.classification,reference.policy_version,reference.integrity_hash,reference.issued_at)
        if actual!=expected or reference.classification!=self.CLASSIFICATION:raise InvalidTerminologyRecord("persisted terminology governance reference mismatch")
        record=self.get(reference.governance_record_id)
        if record is None:raise InvalidTerminologyRecord("exact terminology governance record is unavailable")
        _validate_governance_chain(self._engine,record)
        if (record.version,record.target_concept_id,record.terminology_version,record.source_reference,record.mapping_type,record.policy_version,record.integrity_hash)!=(reference.record_version,reference.target_concept_id,reference.terminology_version,reference.source_reference,reference.mapping_type,reference.policy_version,reference.integrity_hash):raise InvalidTerminologyRecord("terminology governance lineage mismatch")
        if not record.provenance_references or record.integrity_hash!=mapping_governance_integrity_hash(record):raise InvalidTerminologyRecord("terminology governance integrity mismatch")
        return record

def _validate_governance_chain(engine,record):
    stream=record.target_concept_id or "unmapped:"+record.source_reference
    with engine.connect() as connection:payloads=connection.execute(text("SELECT payload FROM terminology_mapping_governance_versions WHERE mapping_stream_id=:stream ORDER BY version"),{"stream":stream}).scalars().all()
    history=tuple(_decode(item) for item in payloads)
    for index,item in enumerate(history,1):
        previous=None if index==1 else history[index-2].governance_record_id
        if item.version!=index or item.predecessor_record_id!=previous or item.integrity_hash!=mapping_governance_integrity_hash(item):raise InvalidTerminologyRecord("terminology governance predecessor chain is invalid")
    if record not in history:raise InvalidTerminologyRecord("terminology governance record is outside canonical history")

def _encode(value):
    data=asdict(value)
    for key,item in tuple(data.items()):
        if isinstance(item,Enum):data[key]=item.value
        elif isinstance(item,datetime):data[key]=item.isoformat()
        elif isinstance(item,tuple):data[key]=list(item)
    return data
def _decode(data):
    value=dict(data);value["source_code_system"]=CodeSystem(value["source_code_system"]) if value["source_code_system"] else None
    value["mapping_type"]=MappingType(value["mapping_type"]);value["mapping_confidence"]=MappingConfidence(value["mapping_confidence"])
    value["review_status"]=MappingReviewStatus(value["review_status"]);value["provenance_references"]=tuple(value["provenance_references"])
    value["created_at"]=datetime.fromisoformat(value["created_at"]);return TerminologyMappingGovernanceRecord(**value)
