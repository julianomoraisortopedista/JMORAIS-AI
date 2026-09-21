from __future__ import annotations
from .domain import ClinicalTimeline, PatientContext
from .ports import PatientContextRepository

class PatientContextVersionConflict(RuntimeError): pass
class PatientContextNotFound(LookupError): pass
class DirectPatientContextWriteProhibited(RuntimeError): pass

class PatientContextService:
    """Versioning/retrieval only; deliberately contains no medical reasoning."""
    def __init__(self, repository: PatientContextRepository): self._repository=repository
    def create(self, context: PatientContext) -> PatientContext:
        raise DirectPatientContextWriteProhibited("Patient Context writes must use ClinicalIngestionService")
    def update(self, context: PatientContext) -> PatientContext:
        raise DirectPatientContextWriteProhibited("Patient Context writes must use ClinicalIngestionService")
    def retrieve(self, patient_id: str) -> PatientContext:
        item=self._repository.latest(patient_id)
        if item is None: raise PatientContextNotFound("patient context does not exist")
        return item
    def version_history(self, patient_id: str) -> tuple[PatientContext,...]: return self._repository.history(patient_id)
    def reconstruct_timeline(self, patient_id: str, *, through_version: int | None=None) -> ClinicalTimeline:
        history=self._repository.history(patient_id)
        if not history: raise PatientContextNotFound("patient context does not exist")
        selected=tuple(item for item in history if through_version is None or item.version<=through_version)
        if not selected: raise PatientContextNotFound("requested context version does not exist")
        entries={entry.entity_id:entry for context in selected for entry in context.timeline.entries}
        latest=selected[-1].timeline
        return ClinicalTimeline(entity_id=latest.entity_id,source=latest.source,author=latest.author,recorded_at=latest.recorded_at,
          confidence=latest.confidence,provenance=latest.provenance,timeline_id=latest.timeline_id,patient_id=latest.patient_id,
          entries=tuple(sorted(entries.values(),key=lambda item:(item.occurred_at,item.entity_id))))
