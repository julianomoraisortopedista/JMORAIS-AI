from .domain import ReasoningInputVersionConflict
class InMemoryClinicalReasoningInputRepository:
    def __init__(self):self._items={};self._subjects={}
    def append(self,value):
        if value.input_id in self._items:raise ReasoningInputVersionConflict("reasoning input is append-only")
        history=self.history(value.subject_reference)
        if history and (value.previous_input_id!=history[-1].input_id or value.input_version!=history[-1].input_version+1):raise ReasoningInputVersionConflict("invalid reasoning-input version chain")
        if not history and (value.input_version!=1 or value.previous_input_id is not None):raise ReasoningInputVersionConflict("reasoning-input history must begin at version 1")
        self._items[value.input_id]=value;self._subjects.setdefault(value.subject_reference,[]).append(value.input_id)
    def get(self,input_id):return self._items.get(input_id)
    def latest(self,subject_reference):
        history=self.history(subject_reference);return history[-1] if history else None
    def history(self,subject_reference):return tuple(self._items[item] for item in self._subjects.get(subject_reference,()))
class InMemoryReasoningInputAuditAdapter:
    def __init__(self):self._events=[]
    def append(self,event):
        if any(item.event_id==event.event_id for item in self._events):raise ReasoningInputVersionConflict("reasoning audit is append-only")
        self._events.append(event)
    def history(self,subject_reference):return tuple(item for item in self._events if item.subject_reference==subject_reference)
