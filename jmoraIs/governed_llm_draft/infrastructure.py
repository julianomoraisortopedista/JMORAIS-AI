from .application import validate_draft_integrity
from .lifecycle import validate_lifecycle_chain
from .domain import *
class InMemoryGovernedLLMDraftRepository:
    def __init__(self,attestor):self._attestor=attestor;self._items={};self._streams={};self._lifecycle={}
    def append(self,value):raise DraftBoundaryRejected("canonical draft issuance requires atomic ACTIVE lifecycle")
    def append_with_lifecycle(self,value,active,supersession=None):
        if not validate_draft_integrity(value,self._attestor):raise DraftBoundaryRejected("draft integrity or issuance attestation is invalid")
        if value.draft_id in self._items:raise DraftVersionConflict("draft history is append-only")
        latest=self.latest(value.draft_stream_id)
        if latest and (value.version!=latest.version+1 or value.predecessor!=latest.draft_id):raise DraftVersionConflict("invalid draft version chain")
        if not latest and (value.version!=1 or value.predecessor is not None):raise DraftVersionConflict("draft history must begin at version 1")
        if active.draft_id!=value.draft_id or not validate_lifecycle_chain((active,)):raise DraftBoundaryRejected("valid ACTIVE genesis is required")
        if latest:
            old=tuple(self._lifecycle.get(latest.draft_id,()))
            if supersession is None or supersession.draft_id!=latest.draft_id or not validate_lifecycle_chain(old+(supersession,)):raise DraftBoundaryRejected("prior draft supersession is required")
        self._items[value.draft_id]=value;self._streams.setdefault(value.draft_stream_id,[]).append(value.draft_id)
        self._lifecycle[value.draft_id]=[active]
        if supersession:self._lifecycle[latest.draft_id].append(supersession)
    def append_lifecycle(self,event):
        draft=self.get(event.draft_id)
        if draft is None or draft.version!=event.draft_version:raise DraftBoundaryRejected("canonical draft is required")
        history=self.lifecycle_history(event.draft_id)
        if not validate_lifecycle_chain(history+(event,)):raise DraftBoundaryRejected("invalid lifecycle chain")
        self._lifecycle[event.draft_id].append(event)
    def get(self,draft_id):return self._items.get(draft_id)
    def history(self,stream_id):return tuple(self._items[x] for x in self._streams.get(stream_id,()))
    def latest(self,stream_id):
        values=self.history(stream_id);return values[-1] if values else None
    def lifecycle_history(self,draft_id):return tuple(self._lifecycle.get(draft_id,()))
    def current_status(self,draft_id,version):
        draft=self.get(draft_id)
        if draft is None or draft.version!=version:return None
        history=self.lifecycle_history(draft_id)
        if not validate_lifecycle_chain(history):raise DraftBoundaryRejected("invalid lifecycle chain")
        return history[-1].resulting_status if history else None
    def current_active(self,stream_id):
        for draft in reversed(self.history(stream_id)):
            if self.current_status(draft.draft_id,draft.version) is GovernedLLMDraftLifecycleStatus.ACTIVE:return draft
        return None
