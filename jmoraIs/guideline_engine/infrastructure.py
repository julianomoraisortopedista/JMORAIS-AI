from .domain import GuidelineBoundaryRejected,PersistedGuidelineRecommendationSetReference,RecommendationVersionConflict
class InMemoryGuidelineQueryAdapter:
    def __init__(self,items):self._items=tuple(items)
    def applicable(self,guideline_ids):return tuple(item for item in self._items if item.guideline_id in guideline_ids)
class InMemoryGuidelineSourceRepository:
    def __init__(self):self._items={}
    def append(self,value):
        history=self.history(value.guideline_id);previous=history[-1] if history else None
        if value.record_id in self._items:raise RecommendationVersionConflict("governed guideline source is append-only")
        if (previous is None and value.record_version!=1) or (previous and (value.record_version!=previous.record_version+1 or value.predecessor_record_id!=previous.record_id)):raise RecommendationVersionConflict("invalid governed guideline predecessor")
        self._items[value.record_id]=value
    def get(self,record_id):return self._items.get(record_id)
    def current(self,guideline_id):
        values=self.history(guideline_id);return values[-1] if values else None
    def history(self,guideline_id):return tuple(sorted((x for x in self._items.values() if x.guideline_id==guideline_id),key=lambda x:x.record_version))
    def applicable(self,guideline_ids):return tuple(x.guideline for identifier in guideline_ids if (x:=self.current(identifier)) is not None)
class InMemoryGovernedTerminologyConceptQueryAdapter:
    def __init__(self,items):self._items={item.canonical_id:item for item in items}
    def get(self,concept_id):return self._items.get(concept_id)
class InMemoryRecommendationRepository:
    def __init__(self):self._items={};self._subjects={};self._references={}
    def append(self,value):
        if value.set_id in self._items:raise RecommendationVersionConflict("recommendation set is append-only")
        history=self.history(value.subject_reference)
        if history and (value.previous_set_id!=history[-1].set_id or value.set_version!=history[-1].set_version+1):raise RecommendationVersionConflict("invalid recommendation version chain")
        if not history and (value.set_version!=1 or value.previous_set_id is not None):raise RecommendationVersionConflict("recommendation history must begin at version 1")
        self._items[value.set_id]=value;self._subjects.setdefault(value.subject_reference,[]).append(value.set_id)
    def latest(self,subject_reference):
        history=self.history(subject_reference);return history[-1] if history else None
    def history(self,subject_reference):return tuple(self._items[item] for item in self._subjects.get(subject_reference,()))
    def reference_for(self,value):
        import json
        from uuid import uuid4
        from jmoraIs.tenancy.context import current_tenant_context
        from .persistence import GuidelineRecommendationJsonCodec,_set_integrity,_validate_chain
        history=self.history(value.subject_reference);_validate_chain(history,value.subject_reference)
        if value not in history:raise GuidelineBoundaryRejected("recommendation set does not match canonical persistence")
        reference=PersistedGuidelineRecommendationSetReference("gsr_"+uuid4().hex,value.set_id,value.set_version,value.subject_reference,current_tenant_context().tenant_id,value.policy_version,_set_integrity(GuidelineRecommendationJsonCodec(),value),value.generated_at)
        self._references[reference.reference_id]=reference;return reference
    def get_exact(self,reference):
        from jmoraIs.tenancy.context import current_tenant_context
        from .persistence import GuidelineRecommendationJsonCodec,_set_integrity,_validate_chain
        if not isinstance(reference,PersistedGuidelineRecommendationSetReference) or self._references.get(reference.reference_id)!=reference:raise GuidelineBoundaryRejected("owner-issued guideline-set reference is required")
        if reference.tenant_id!=current_tenant_context().tenant_id:raise GuidelineBoundaryRejected("guideline-set reference tenant mismatch")
        history=self.history(reference.subject_reference);_validate_chain(history,reference.subject_reference)
        matches=tuple(x for x in history if x.set_id==reference.set_id and x.set_version==reference.set_version)
        if len(matches)!=1:raise GuidelineBoundaryRejected("exact persisted guideline set is unavailable")
        value=matches[0]
        if value.policy_version!=reference.policy_version or not value.provenance_references or _set_integrity(GuidelineRecommendationJsonCodec(),value)!=reference.integrity_hash:raise GuidelineBoundaryRejected("persisted guideline-set reference mismatch")
        return value
class InMemoryRecommendationAuditAdapter:
    def __init__(self):self._items=[]
    def append(self,event):
        if any(item.event_id==event.event_id for item in self._items):raise RecommendationVersionConflict("recommendation audit is append-only")
        self._items.append(event)
    def history(self,subject_reference):return tuple(item for item in self._items if item.subject_reference==subject_reference)
