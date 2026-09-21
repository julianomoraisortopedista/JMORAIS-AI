from __future__ import annotations
import json
from sqlalchemy import text
from .domain import GovernedGuidelineRecord,RecommendationVersionConflict
from .persistence import GuidelineRecommendationJsonCodec

class PostgreSQLGuidelineSourceRepository:
    def __init__(self,engine,codec=None):self._engine=engine;self._codec=codec or GuidelineRecommendationJsonCodec()
    def append(self,value):
        previous=self.current(value.guideline_id)
        if (previous is None and value.record_version!=1) or (previous and (value.record_version!=previous.record_version+1 or value.predecessor_record_id!=previous.record_id)):raise RecommendationVersionConflict("invalid governed guideline predecessor")
        with self._engine.begin() as connection:connection.execute(text("""INSERT INTO governed_guideline_source_versions
          (record_id,guideline_id,source_version_identifier,record_version,predecessor_record_id,governance_status,appraisal_reference,appraisal_version,provenance_references,policy_version,created_at,payload)
          VALUES(:record,:guideline,:source,:version,:predecessor,:status,:appraisal,:appraisal_version,CAST(:provenance AS jsonb),:policy,:created,CAST(:payload AS jsonb))"""),
          {"record":value.record_id,"guideline":value.guideline_id,"source":value.source_version_identifier,"version":value.record_version,"predecessor":value.predecessor_record_id,"status":value.governance_status,"appraisal":value.appraisal_reference,"appraisal_version":value.appraisal_version,"provenance":json.dumps(value.provenance_references),"policy":value.policy_version,"created":value.created_at,"payload":json.dumps(self._codec.encode(value.guideline),sort_keys=True,separators=(",",":"))})
    def get(self,record_id):return self._one("record_id",record_id)
    def current(self,guideline_id):
        values=self.history(guideline_id);return values[-1] if values else None
    def history(self,guideline_id):return self._many("guideline_id",guideline_id)
    def applicable(self,guideline_ids):
        return tuple(record.guideline for identifier in guideline_ids if (record:=self.current(identifier)) is not None)
    def _one(self,column,value):
        values=self._rows(column,value);return self._decode(values[0]) if values else None
    def _many(self,column,value):return tuple(self._decode(row) for row in self._rows(column,value))
    def _rows(self,column,value):
        with self._engine.connect() as connection:return connection.execute(text(f"SELECT * FROM governed_guideline_source_versions WHERE {column}=:value ORDER BY record_version"),{"value":value}).mappings().all()
    def _decode(self,row):return GovernedGuidelineRecord(row["record_id"],row["guideline_id"],row["source_version_identifier"],row["record_version"],row["predecessor_record_id"],row["governance_status"],self._codec.decode(row["payload"]),row["appraisal_reference"],row["appraisal_version"],tuple(row["provenance_references"]),row["policy_version"],row["created_at"])
