from .domain import *
class InMemoryGovernedOrthopedicStateQueryAdapter:
    def __init__(self,items):self._items={item.state_reference_id:item for item in items}
    def get(self,identifier):return self._items.get(identifier)
class InMemoryOrthopedicAssessmentRepository:
    def __init__(self):self._items={};self._subjects={};self._references={}
    def append(self,value):
        if value.set_id in self._items:raise OrthopedicVersionConflict("orthopedic assessment is append-only")
        history=self.history(value.subject_reference)
        if history and (value.previous_set_id!=history[-1].set_id or value.set_version!=history[-1].set_version+1):raise OrthopedicVersionConflict("invalid assessment version chain")
        if not history and (value.set_version!=1 or value.previous_set_id is not None):raise OrthopedicVersionConflict("assessment history must begin at version 1")
        self._items[value.set_id]=value;self._subjects.setdefault(value.subject_reference,[]).append(value.set_id)
    def latest(self,subject):
        values=self.history(subject);return values[-1] if values else None
    def history(self,subject):return tuple(self._items[item] for item in self._subjects.get(subject,()))
    def reference_for(self,value):
        from uuid import uuid4
        from jmoraIs.tenancy.context import current_tenant_context
        from .persistence import OrthopedicJsonCodec,_set_integrity,_validate_chain
        history=self.history(value.subject_reference);_validate_chain(history,value.subject_reference)
        if value not in history:raise OrthopedicBoundaryError("assessment set does not match canonical persistence")
        reference=PersistedOrthopedicAssessmentSetReference("osr_"+uuid4().hex,value.set_id,value.set_version,value.subject_reference,current_tenant_context().tenant_id,value.assessment.policy_version,_set_integrity(OrthopedicJsonCodec(),value),value.generated_at)
        self._references[reference.reference_id]=reference;return reference
    def get_exact(self,reference):
        from jmoraIs.tenancy.context import current_tenant_context
        from .persistence import OrthopedicJsonCodec,_set_integrity,_validate_chain
        if not isinstance(reference,PersistedOrthopedicAssessmentSetReference) or self._references.get(reference.reference_id)!=reference:raise OrthopedicBoundaryError("owner-issued orthopedic-set reference is required")
        if reference.tenant_id!=current_tenant_context().tenant_id:raise OrthopedicBoundaryError("orthopedic-set reference tenant mismatch")
        history=self.history(reference.subject_reference);_validate_chain(history,reference.subject_reference)
        matches=tuple(x for x in history if x.set_id==reference.set_id and x.set_version==reference.set_version)
        if len(matches)!=1:raise OrthopedicBoundaryError("exact persisted orthopedic set is unavailable")
        value=matches[0]
        if value.assessment.policy_version!=reference.policy_version or not value.assessment.provenance_references or _set_integrity(OrthopedicJsonCodec(),value)!=reference.integrity_hash:raise OrthopedicBoundaryError("persisted orthopedic-set reference mismatch")
        return value
class InMemoryOrthopedicAuditAdapter:
    def __init__(self):self._items=[]
    def append(self,event):
        if any(item.event_id==event.event_id for item in self._items):raise OrthopedicVersionConflict("orthopedic audit is append-only")
        self._items.append(event)
    def history(self,subject):return tuple(item for item in self._items if item.subject_reference==subject)
