from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from hashlib import sha256
import json

from .domain import PatientContext


class PatientContextExactReferenceError(RuntimeError): pass
class PatientContextReferenceRejected(PatientContextExactReferenceError): pass
class LegacyMissingPersistedPatientContextReference(PatientContextExactReferenceError): pass


@dataclass(frozen=True)
class PersistedPatientContextReference:
    reference_id: str
    context_id: str
    version: int
    pseudonymous_patient_id: str
    tenant_id: str
    policy_version: str
    authorized_ingestion_record_id: str
    context_integrity_hash: str
    integrity_hash: str
    issued_at: datetime

    def __post_init__(self):
        required = (self.reference_id, self.context_id, self.pseudonymous_patient_id,
                    self.tenant_id, self.policy_version, self.authorized_ingestion_record_id,
                    self.context_integrity_hash, self.integrity_hash)
        if any(not isinstance(value, str) or not value.strip() for value in required):
            raise PatientContextReferenceRejected("complete PatientContext reference metadata is required")
        if self.version < 1:
            raise PatientContextReferenceRejected("PatientContext reference version must be positive")
        if len(self.context_integrity_hash) != 64 or len(self.integrity_hash) != 64:
            raise PatientContextReferenceRejected("PatientContext reference hashes must be SHA-256")
        if self.issued_at.tzinfo is None:
            raise PatientContextReferenceRejected("PatientContext reference timestamp must be timezone-aware")


def context_integrity(codec, context: PatientContext) -> str:
    return sha256(json.dumps(codec.encode(context), sort_keys=True,
        separators=(",", ":")).encode()).hexdigest()


def reference_integrity(reference: PersistedPatientContextReference) -> str:
    payload = asdict(reference); payload.pop("integrity_hash")
    payload["issued_at"] = reference.issued_at.isoformat()
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate_reference_integrity(reference: PersistedPatientContextReference) -> bool:
    return reference_integrity(reference) == reference.integrity_hash
