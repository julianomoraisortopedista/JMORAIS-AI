"""Historical event identity is separate from current-use eligibility."""
from dataclasses import asdict, dataclass
from hashlib import sha256
import json


class LifecycleAuthorityRejected(RuntimeError):
    pass


@dataclass(frozen=True)
class PersistedEvidenceLifecycleReference:
    tenant_id: str
    governed_evidence_id: str
    event_id: str
    stream_position: int
    status: str
    policy_version: str
    event_hash: str

    def __post_init__(self):
        if (not all(isinstance(x, str) and x.strip() for x in (
                self.tenant_id, self.governed_evidence_id, self.event_id,
                self.status, self.policy_version, self.event_hash))
                or self.stream_position < 1 or len(self.event_hash) != 64):
            raise LifecycleAuthorityRejected('complete exact lifecycle identity required')

    def payload(self):
        return asdict(self)


def verify_event(row, reference=None):
    """Independent canonical event verification, also used by replay."""
    from .governance_persistence import _lifecycle
    if row is None:
        raise LifecycleAuthorityRejected('exact lifecycle event missing')
    event = _lifecycle(row['payload'])
    payload = dict(row['payload'])
    payload.pop('event_hash')
    digest = sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if (digest != event.event_hash or
        (row['event_id'], row['governed_evidence_id'], row['event_hash'],
         row['previous_event_hash'], row['occurred_at']) !=
        (event.event_id, event.governed_evidence_id, event.event_hash,
         event.previous_event_hash, event.occurred_at)):
        raise LifecycleAuthorityRejected('lifecycle event integrity rejected')
    canonical = PersistedEvidenceLifecycleReference(row['tenant_id'], event.governed_evidence_id,
        event.event_id, row['stream_position'], event.status.value, event.policy_version, event.event_hash)
    if reference is not None and canonical != reference:
        raise LifecycleAuthorityRejected('lifecycle exact reference mismatch')
    return event, canonical
