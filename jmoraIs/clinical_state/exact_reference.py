from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from hashlib import sha256
import json


class ClinicalStateExactReferenceError(RuntimeError): pass
class ClinicalStateReferenceRejected(ClinicalStateExactReferenceError): pass
class ClinicalStateTimelineReferenceRejected(ClinicalStateExactReferenceError): pass
class LegacyMissingClinicalStateReference(ClinicalStateExactReferenceError): pass
class LegacyMissingClinicalStateTimelineReference(ClinicalStateExactReferenceError): pass


def _hash(payload) -> str:
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class PersistedClinicalStateReference:
    reference_id: str
    state_id: str
    state_version: int
    pseudonymous_patient_id: str
    tenant_id: str
    policy_version: str
    predecessor_reference_id: str | None
    predecessor_state_version: int | None
    provenance_reference: str
    state_integrity_hash: str
    integrity_hash: str
    issued_at: datetime

    def __post_init__(self):
        required = (self.reference_id, self.state_id, self.pseudonymous_patient_id,
                    self.tenant_id, self.policy_version, self.provenance_reference,
                    self.state_integrity_hash, self.integrity_hash)
        if any(not isinstance(value, str) or not value.strip() for value in required):
            raise ClinicalStateReferenceRejected("complete Clinical State reference metadata is required")
        if self.state_version < 1 or len(self.state_integrity_hash) != 64 or len(self.integrity_hash) != 64:
            raise ClinicalStateReferenceRejected("Clinical State reference version and hashes are invalid")
        if self.state_version == 1 and (self.predecessor_reference_id is not None or self.predecessor_state_version is not None):
            raise ClinicalStateReferenceRejected("genesis Clinical State reference cannot have a predecessor")
        if self.state_version > 1 and (not self.predecessor_reference_id or self.predecessor_state_version != self.state_version - 1):
            raise ClinicalStateReferenceRejected("Clinical State predecessor reference is required")
        if self.issued_at.tzinfo is None:
            raise ClinicalStateReferenceRejected("Clinical State reference timestamp must be timezone-aware")


@dataclass(frozen=True)
class PersistedClinicalStateTimelineReference:
    timeline_reference_id: str
    pseudonymous_patient_id: str
    tenant_id: str
    policy_version: str
    state_references: tuple[PersistedClinicalStateReference, ...]
    integrity_hash: str
    issued_at: datetime

    def __post_init__(self):
        required = (self.timeline_reference_id, self.pseudonymous_patient_id,
                    self.tenant_id, self.policy_version, self.integrity_hash)
        if any(not isinstance(value, str) or not value.strip() for value in required):
            raise ClinicalStateTimelineReferenceRejected("complete timeline reference metadata is required")
        if not self.state_references or len(self.integrity_hash) != 64:
            raise ClinicalStateTimelineReferenceRejected("timeline members and SHA-256 integrity are required")
        if self.issued_at.tzinfo is None:
            raise ClinicalStateTimelineReferenceRejected("timeline reference timestamp must be timezone-aware")


def state_integrity(codec, state) -> str:
    return _hash(codec.encode(state))


def state_provenance_reference(state) -> str:
    return "clinical-state-provenance:" + _hash(list(state.provenance_references))


def reference_integrity(reference: PersistedClinicalStateReference) -> str:
    payload = asdict(reference); payload.pop("integrity_hash")
    payload["issued_at"] = reference.issued_at.isoformat()
    return _hash(payload)


def validate_reference_integrity(reference) -> bool:
    return isinstance(reference, PersistedClinicalStateReference) and reference_integrity(reference) == reference.integrity_hash


def timeline_integrity(reference: PersistedClinicalStateTimelineReference) -> str:
    payload = {"timeline_reference_id": reference.timeline_reference_id,
        "pseudonymous_patient_id": reference.pseudonymous_patient_id,
        "tenant_id": reference.tenant_id, "policy_version": reference.policy_version,
        "state_references": [item.integrity_hash for item in reference.state_references],
        "issued_at": reference.issued_at.isoformat()}
    return _hash(payload)


def validate_timeline_integrity(reference) -> bool:
    return isinstance(reference, PersistedClinicalStateTimelineReference) and timeline_integrity(reference) == reference.integrity_hash
