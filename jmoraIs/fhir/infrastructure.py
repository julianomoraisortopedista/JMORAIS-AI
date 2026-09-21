from __future__ import annotations

from jmoraIs.terminology.domain import CodeSystem, MappingOutcome
from .domain import FhirCodeDecision


FHIR_SYSTEMS={
    "http://snomed.info/sct":CodeSystem.SNOMED_CT,
    "http://loinc.org":CodeSystem.LOINC,
    "http://www.nlm.nih.gov/research/umls/rxnorm":CodeSystem.RXNORM,
    "http://hl7.org/fhir/sid/icd-10":CodeSystem.ICD_10,
}


class CanonicalFhirTerminologyAdapter:
    """Translates FHIR system URIs, while canonical terminology remains authoritative."""
    def __init__(self,query_port,versions): self._query=query_port;self._versions=dict(versions)
    def validate(self,system,code,display):
        code_system=FHIR_SYSTEMS.get(system);version=self._versions.get(code_system)
        if code_system is None or not version:return FhirCodeDecision(False,True,None,("UNKNOWN_CODE_SYSTEM",))
        result=self._query.resolve(code,code_system,version)
        accepted=result.outcome is MappingOutcome.MAPPED and not result.review_required
        selected=result.candidates[0].preferred_term if accepted else None
        return FhirCodeDecision(accepted,result.review_required or not accepted,selected,
            result.provenance_references)


class InMemoryFhirIdempotencyQueryAdapter:
    def __init__(self): self._items={}
    def record(self,source_reference_id,reference): self._items.setdefault(source_reference_id,reference)
    def find(self,source_reference_id): return self._items.get(source_reference_id)
