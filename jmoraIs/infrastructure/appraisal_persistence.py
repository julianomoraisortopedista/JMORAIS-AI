from __future__ import annotations
from dataclasses import asdict
from datetime import date,datetime
from enum import Enum
import json
from sqlalchemy import text
from jmoraIs.appraisal.domain import *

def _json(value):
    if isinstance(value,Enum):return value.name
    if isinstance(value,(date,datetime)):return value.isoformat()
    raise TypeError(type(value).__name__)

class PostgreSQLClinicalAppraisalRepository:
    def __init__(self,engine):self._engine=engine
    def append(self,value):
        previous=self.current(value.recommendation_reference)
        if (previous is None and value.appraisal_version!=1) or (previous and (value.appraisal_version!=previous.appraisal_version+1 or value.predecessor_appraisal_id!=previous.appraisal_id)):
            raise AppraisalInvariantError("invalid appraisal predecessor")
        payload=json.loads(json.dumps({"appraisal":asdict(value.appraisal),"request":asdict(value.source_request)},default=_json))
        with self._engine.begin() as connection:
            connection.execute(text("""INSERT INTO clinical_appraisal_records
              (appraisal_id,evidence_package_id,recommendation_reference,framework,framework_version,appraisal_version,
               predecessor_appraisal_id,status,payload,provenance_references,reviewer_reference,reviewer_status,
               policy_version,created_at,superseded_by,integrity_hash)
              VALUES(:appraisal_id,:evidence_package_id,:recommendation_reference,:framework,:framework_version,:appraisal_version,
               :predecessor_appraisal_id,:status,CAST(:payload AS jsonb),CAST(:provenance AS jsonb),:reviewer_reference,:reviewer_status,
               :policy_version,:created_at,:superseded_by,:integrity_hash)"""),{**value.__dict__,"status":value.status.value,
               "payload":json.dumps(payload),"provenance":json.dumps(value.provenance_references)})
    def get(self,appraisal_id):return self._one("appraisal_id=:value",appraisal_id)
    def current(self,recommendation_reference):
        values=self.history(recommendation_reference);return values[-1] if values else None
    def history(self,recommendation_reference):return self._many("recommendation_reference=:value",recommendation_reference)
    def by_evidence_package(self,evidence_package_id):return self._many("evidence_package_id=:value",evidence_package_id)
    def _one(self,predicate,value):
        values=self._rows(predicate,value);return _decode(values[0]) if values else None
    def _many(self,predicate,value):return tuple(_decode(x) for x in self._rows(predicate,value))
    def _rows(self,predicate,value):
        with self._engine.connect() as connection:return connection.execute(text(f"SELECT * FROM clinical_appraisal_records WHERE {predicate} ORDER BY appraisal_version"),{"value":value}).mappings().all()

def _decode(row):
    p=row["payload"];a=p["appraisal"];e=a["explainability"];r=p["request"];q=r["methodological_quality"];g=r["guideline"]
    explanation=RecommendationExplainability(EvidenceLevel(e["evidence_level"]),MethodologicalQuality[e["methodological_quality"]],e["methodological_quality_score"],RecommendationStrength(e["recommendation_strength"]),e["guideline_authority"],tuple(ConflictType[x] for x in e["conflicts_detected"]),tuple(ApplicabilityContext[x] for x in e["applicability"]),tuple(e["limitations"]))
    appraisal=AppraisedRecommendation(a["recommendation_id"],a["topic_id"],a["recommendation"],a["evidence_package_id"],RecommendationValidity[a["recommendation_validity"]],a["eligible_for_clinical_intelligence"],explanation,tuple(a["provenance_references"]),tuple(a["ledger_references"]),a["policy_version"])
    quality=MethodologicalQualityAssessment(RiskOfBias[q["risk_of_bias"]],*(AssessmentRating[q[x]] for x in ("randomization","allocation_concealment","blinding","attrition","selective_reporting","external_validity","statistical_robustness")),tuple(q["limitations"]))
    guideline=GuidelineGovernance(g["guideline_id"],g["issuing_organization"],date.fromisoformat(g["publication_date"]),date.fromisoformat(g["revision_date"]) if g["revision_date"] else None,date.fromisoformat(g["expiration_date"]) if g["expiration_date"] else None,g["superseded_by_guideline_id"],date.fromisoformat(g["withdrawn_at"]) if g["withdrawn_at"] else None,tuple(g["regional_applicability"]),tuple(g["specialty_applicability"]))
    request=AppraisalRequest(r["recommendation_id"],r["topic_id"],r["recommendation"],r["evidence_package_id"],EvidenceLevel(r["evidence_level"]),quality,RecommendationStrength(r["recommendation_strength"]),guideline,tuple(ApplicabilityContext[x] for x in r["applicability"]),tuple(r["limitations"]))
    return ClinicalAppraisalRecord(row["appraisal_id"],row["evidence_package_id"],row["recommendation_reference"],row["framework"],row["framework_version"],row["appraisal_version"],row["predecessor_appraisal_id"],AppraisalRecordStatus(row["status"]),appraisal,request,tuple(row["provenance_references"]),row["reviewer_reference"],row["reviewer_status"],row["policy_version"],row["created_at"],row["superseded_by"],row["integrity_hash"])
