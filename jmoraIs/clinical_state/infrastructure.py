from __future__ import annotations
from .domain import ClinicalStateVersionConflict

class InMemoryClinicalStateRepository:
    def __init__(self): self._items={};self._patients={}
    def append(self,state):
        if state.state_id in self._items: raise ClinicalStateVersionConflict("state is append-only")
        history=self.history(state.pseudonymous_patient_id)
        if history and (state.previous_state_id!=history[-1].state_id or state.state_version!=history[-1].state_version+1): raise ClinicalStateVersionConflict("invalid state version chain")
        if not history and (state.state_version!=1 or state.previous_state_id is not None): raise ClinicalStateVersionConflict("state history must begin at version 1")
        self._items[state.state_id]=state;self._patients.setdefault(state.pseudonymous_patient_id,[]).append(state.state_id)
    def get(self,state_id):return self._items.get(state_id)
    def latest(self,patient_id):
        history=self.history(patient_id);return history[-1] if history else None
    def at(self,patient_id,as_of):
        items=tuple(item for item in self.history(patient_id) if item.as_of<=as_of);return items[-1] if items else None
    def history(self,patient_id): return tuple(self._items[item] for item in self._patients.get(patient_id,()))

class InMemoryClinicalStateAuditAdapter:
    def __init__(self): self._events=[]
    def append(self,event):
        if any(item.event_id==event.event_id for item in self._events): raise ClinicalStateVersionConflict("audit is append-only")
        self._events.append(event)
    def history(self,patient_id): return tuple(item for item in self._events if item.patient_id==patient_id)

class DeterministicClinicalNormalizer:
    def __init__(self,mappings=()): self._mappings={(category,source.casefold()):target for category,source,target in mappings}
    def normalize(self,category,value): return self._mappings.get((category,value.casefold()))

class AuthorizedPatientContextQueryAdapter:
    """Adapter is composed with an already authorized Patient Context access boundary."""
    def __init__(self,history_loader): self._history_loader=history_loader
    def history(self,patient_id): return tuple(self._history_loader(patient_id))
    def current(self,patient_id):
        history=self.history(patient_id)
        if not history: raise LookupError("authorized Patient Context not found")
        return history[-1]
    def at(self,patient_id,as_of):
        history=tuple(item for item in self.history(patient_id) if item.effective_at<=as_of)
        if not history: raise LookupError("authorized Patient Context not found at timestamp")
        return history[-1]
