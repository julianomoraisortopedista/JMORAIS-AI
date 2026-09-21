from __future__ import annotations
from hashlib import sha256
from .domain import *

class ClinicalTerminologyService:
    """Deterministic terminology operations only; no clinical interpretation."""
    def __init__(self,repository,audit,units,*,clock):self._repository=repository;self._audit=audit;self._units=units;self._clock=clock
    def normalize_terminology(self,term,code_system,version,*,actor_id="system"):
        result=self._resolve(term,code_system,version)
        kind=TerminologyAuditType.AMBIGUOUS_MAPPING if result.outcome is MappingOutcome.REVIEW_REQUIRED else TerminologyAuditType.NORMALIZATION
        self._event(kind,term,actor_id,version,result.outcome.value,result.provenance_references[0] if result.provenance_references else "no-candidate")
        return result
    def resolve_concepts(self,term,code_system,version,*,actor_id="system"):return self.normalize_terminology(term,code_system,version,actor_id=actor_id)
    def map_codes(self,source_codes,target_system,*,actor_id="system"):
        if not isinstance(source_codes,tuple) or not source_codes:raise InvalidTerminologyRecord("typed source codes are required")
        results=self._repository.mappings(source_codes,target_system)
        outcome="UNKNOWN" if not results else ("REVIEW_REQUIRED" if len(results)>1 or any(len(item.target_codes)>1 for item in results) else "MAPPED")
        self._event(TerminologyAuditType.AMBIGUOUS_MAPPING if outcome=="REVIEW_REQUIRED" else TerminologyAuditType.MAPPING,
          "|".join(item.code for item in source_codes),actor_id,source_codes[0].version,outcome,results[0].provenance if results else "no-mapping")
        return results
    def validate_concept(self,concept,*,as_of,actor_id="system"):
        if not isinstance(concept,ClinicalConcept):raise InvalidTerminologyRecord("typed ClinicalConcept is required")
        issues=[]
        if concept.status is not TerminologyStatus.ACTIVE:issues.append(concept.status.value)
        if as_of<concept.effective_date:issues.append("NOT_YET_EFFECTIVE")
        if concept.retirement_date and as_of>=concept.retirement_date:issues.append("RETIRED_BY_DATE")
        if self._repository.version(concept.code_system,concept.version) is None:issues.append("UNKNOWN_VERSION")
        result=ConceptValidation(concept.canonical_id,not issues,concept.status,tuple(issues),self._clock())
        self._event(TerminologyAuditType.VALIDATION,concept.canonical_id,actor_id,concept.version,"VALID" if result.valid else "INVALID",concept.provenance);return result
    def version_lookup(self,code_system,version,*,actor_id="system"):
        result=self._repository.version(code_system,version)
        self._event(TerminologyAuditType.VERSION_LOOKUP,code_system.value,actor_id,version,"FOUND" if result else "UNKNOWN","version-registry")
        if result is None:raise InvalidTerminologyRecord("terminology version does not exist")
        return result
    def normalize_unit(self,value,unit,target_unit,version,*,actor_id="system"):
        result=self._units.normalize(value,unit,target_unit,version)
        self._event(TerminologyAuditType.NORMALIZATION,f"{unit}->{target_unit}",actor_id,version,"NORMALIZED",result.conversion_provenance);return result
    def _resolve(self,term,code_system,version):
        if not isinstance(term,str) or not term.strip():raise InvalidTerminologyRecord("clinical term is required")
        candidates=self._repository.search(term,code_system,version)
        provenance=tuple(item.provenance for item in candidates)
        if not candidates:return MappedClinicalConcept(term,code_system,version,MappingOutcome.UNKNOWN,(),None,MappingConfidence.UNKNOWN,True,())
        if len(candidates)>1:return MappedClinicalConcept(term,code_system,version,MappingOutcome.REVIEW_REQUIRED,candidates,None,MappingConfidence.UNKNOWN,True,provenance)
        item=candidates[0];confidence=MappingConfidence.HIGH if term.casefold()==item.preferred_term.casefold() or any(term.casefold()==code.code.casefold() for code in item.codes) else MappingConfidence.MEDIUM
        return MappedClinicalConcept(term,code_system,version,MappingOutcome.MAPPED,candidates,item.canonical_id,confidence,item.status is not TerminologyStatus.ACTIVE,provenance)
    def _event(self,kind,subject,actor,version,outcome,provenance):
        event_id="ta_"+sha256(f"{kind.value}|{subject}|{version}|{outcome}|{len(self._audit.history(subject))}".encode()).hexdigest()
        self._audit.append(TerminologyAuditEvent(event_id,kind,subject,self._clock(),actor,version,outcome,provenance))
