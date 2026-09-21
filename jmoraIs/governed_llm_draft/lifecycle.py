from __future__ import annotations
import json
from dataclasses import asdict,replace
from hashlib import sha256
from jmoraIs.tenancy.context import current_tenant_context
from .application import validate_draft_integrity
from .domain import *

def lifecycle_hash(event):
    material=asdict(event);material["integrity_hash"]=""
    return sha256(json.dumps(material,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()
def lifecycle_event(draft,status,reason,actor,policy,occurred_at,history=()):
    previous=history[-1] if history else None;prior=previous.resulting_status if previous else None;position=len(history)+1
    identifier="draft_lifecycle_"+sha256((draft.draft_id+"|"+str(position)+"|"+status.value+"|"+reason).encode()).hexdigest()
    unsigned=GovernedLLMDraftLifecycleEvent(identifier,draft.draft_id,draft.version,draft.tenant_id,prior,status,reason,actor,policy,occurred_at,position,previous.lifecycle_event_id if previous else None,previous.integrity_hash if previous else None,"")
    return replace(unsigned,integrity_hash=lifecycle_hash(unsigned))
def validate_lifecycle_chain(events):
    for index,event in enumerate(events):
        previous=events[index-1] if index else None
        if event.stream_position!=index+1 or event.integrity_hash!=lifecycle_hash(event):return False
        if previous is None:
            if event.prior_status is not None or event.predecessor_event_id is not None or event.previous_hash is not None or event.resulting_status is not GovernedLLMDraftLifecycleStatus.ACTIVE:return False
        elif event.prior_status is not previous.resulting_status or event.predecessor_event_id!=previous.lifecycle_event_id or event.previous_hash!=previous.integrity_hash:return False
    return True
class GovernedLLMDraftLifecycleService:
    ALLOWED={GovernedLLMDraftLifecycleStatus.ACTIVE:{GovernedLLMDraftLifecycleStatus.SUPERSEDED,GovernedLLMDraftLifecycleStatus.INVALIDATED}}
    def __init__(self,drafts,lifecycle,draft_attestor,*,clock):self._drafts=drafts;self._lifecycle=lifecycle;self._draft_attestor=draft_attestor;self._clock=clock
    def transition(self,draft_id,version,target,*,reason_reference,actor_reference,policy_version):
        draft=self._drafts.get(draft_id)
        if draft is None or draft.version!=version:raise DraftBoundaryRejected("canonical draft and exact version are required")
        if not validate_draft_integrity(draft,self._draft_attestor):raise DraftBoundaryRejected("draft integrity is invalid")
        if draft.tenant_id!=current_tenant_context().tenant_id:raise DraftBoundaryRejected("draft tenant mismatch")
        history=self._lifecycle.lifecycle_history(draft_id)
        if not validate_lifecycle_chain(history):raise DraftBoundaryRejected("draft lifecycle chain is invalid")
        current=history[-1].resulting_status if history else None
        if target not in self.ALLOWED.get(current,set()):raise DraftBoundaryRejected("invalid draft lifecycle transition")
        if not reason_reference.strip() or not actor_reference.strip() or not policy_version.strip():raise DraftBoundaryRejected("lifecycle attribution is required")
        event=lifecycle_event(draft,target,reason_reference,actor_reference,policy_version,self._clock(),history);self._lifecycle.append_lifecycle(event);return event
    def current_status(self,draft_id,version):return self._lifecycle.current_status(draft_id,version)
