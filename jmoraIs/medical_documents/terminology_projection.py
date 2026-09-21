from __future__ import annotations
from jmoraIs.terminology.domain import ClinicalConcept,TerminologyStatus
from .domain import DocumentTerminologyReference

class GovernedDocumentTerminologyProjection:
    POLICY="MIP-08-TERMINOLOGY-1"
    def project(self,value):
        if not isinstance(value,ClinicalConcept):return None
        active=value.status is TerminologyStatus.ACTIVE
        status="MAPPED" if active else value.status.value
        confidence="HIGH" if active else "UNKNOWN"
        return DocumentTerminologyReference(value.canonical_id,value.display_name,value.preferred_term,value.version,status,confidence,not active,(value.provenance,value.source.provenance),value.code_system.value,self.POLICY)
