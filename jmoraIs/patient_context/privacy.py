from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime
from enum import Enum
from hashlib import sha256
import json
from typing import Optional

from .domain import PatientContextInvariantError, _required


class ClinicalDataClass(str, Enum):
    DIRECT_IDENTIFIER = "DIRECT_IDENTIFIER"
    INDIRECT_IDENTIFIER = "INDIRECT_IDENTIFIER"
    CLINICAL_SENSITIVE = "CLINICAL_SENSITIVE"
    CLINICAL_NON_IDENTIFYING = "CLINICAL_NON_IDENTIFYING"
    OPERATIONAL = "OPERATIONAL"
    SCIENTIFIC_REFERENCE = "SCIENTIFIC_REFERENCE"


class SensitivityLevel(str, Enum):
    RESTRICTED = "RESTRICTED"
    HIGH = "HIGH"
    MODERATE = "MODERATE"
    LOW = "LOW"


class PurposeOfUse(str, Enum):
    CLINICAL_DOCUMENTATION = "CLINICAL_DOCUMENTATION"
    RETROSPECTIVE_REVIEW = "RETROSPECTIVE_REVIEW"
    SCIENTIFIC_VALIDATION = "SCIENTIFIC_VALIDATION"
    AUDIT_SUPPORT = "AUDIT_SUPPORT"
    QUALITY_IMPROVEMENT = "QUALITY_IMPROVEMENT"
    RESEARCH_PREPARATION = "RESEARCH_PREPARATION"


class LegalBasisType(str, Enum):
    CONSENT = "CONSENT"
    HEALTHCARE_PROVISION = "HEALTHCARE_PROVISION"
    LEGAL_OBLIGATION = "LEGAL_OBLIGATION"
    RESEARCH_AUTHORIZATION = "RESEARCH_AUTHORIZATION"
    INSTITUTIONAL_AUTHORIZATION = "INSTITUTIONAL_AUTHORIZATION"


class DeidentificationStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    DEIDENTIFIED = "DEIDENTIFIED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    FAILED = "FAILED"


class ClinicalAuditEventType(str, Enum):
    INGESTION = "INGESTION"
    IDENTITY_LOOKUP = "IDENTITY_LOOKUP"
    AUTHORIZATION_DENIAL = "AUTHORIZATION_DENIAL"
    DEIDENTIFICATION_FAILURE = "DEIDENTIFICATION_FAILURE"
    CONTEXT_ACCESS = "CONTEXT_ACCESS"
    PURPOSE_MISMATCH = "PURPOSE_MISMATCH"

class ClinicalDataBoundaryError(RuntimeError): pass
class ClinicalAuthorizationDenied(ClinicalDataBoundaryError): pass
class PurposeNotAllowed(ClinicalDataBoundaryError): pass
class IdentityBoundaryViolation(ClinicalDataBoundaryError): pass
class DirectIdentifierDetected(IdentityBoundaryViolation): pass
class DeidentificationRequired(ClinicalDataBoundaryError): pass
class DeidentificationFailed(ClinicalDataBoundaryError): pass
class InvalidClinicalSource(ClinicalDataBoundaryError): pass
class InsufficientProvenance(ClinicalDataBoundaryError): pass


@dataclass(frozen=True)
class DataClassification:
    data_class: ClinicalDataClass
    sensitivity: SensitivityLevel


@dataclass(frozen=True)
class ClassifiedClinicalField:
    name: str
    value: str
    classification: DataClassification
    free_text: bool = False
    def __post_init__(self):
        _required(self.name, "field name")


@dataclass(frozen=True)
class ActorContext:
    actor_id: str
    role: str
    organization_id: str
    def __post_init__(self):
        _required(self.actor_id, "actor_id"); _required(self.role, "role"); _required(self.organization_id, "organization_id")


@dataclass(frozen=True)
class AuthorizationRequest:
    actor: ActorContext
    patient_scope: str
    purpose: PurposeOfUse
    requested_classes: tuple[ClinicalDataClass, ...]
    requested_at: datetime
    policy_version: str
    def __post_init__(self):
        _required(self.patient_scope, "patient_scope"); _required(self.policy_version, "policy_version")
        if self.requested_at.tzinfo is None: raise PatientContextInvariantError("authorization timestamp must be timezone-aware")
        if not self.requested_classes: raise PatientContextInvariantError("requested data classes are required")


@dataclass(frozen=True)
class AuthorizationDecision:
    allowed: bool
    decision_id: str
    policy_version: str
    decided_at: datetime
    reason_code: str


@dataclass(frozen=True)
class LegalBasis:
    basis_id: str
    basis_type: LegalBasisType
    patient_scope: str
    purposes: tuple[PurposeOfUse, ...]
    valid_from: datetime
    valid_until: Optional[datetime]
    source: str
    policy_version: str
    restrictions: tuple[str, ...] = ()
    def __post_init__(self):
        for value, name in ((self.basis_id,"basis_id"),(self.patient_scope,"patient_scope"),(self.source,"source"),(self.policy_version,"policy_version")): _required(value,name)
        if self.valid_from.tzinfo is None or (self.valid_until and self.valid_until.tzinfo is None): raise PatientContextInvariantError("legal basis timestamps must be timezone-aware")
        if self.valid_until and self.valid_until < self.valid_from: raise PatientContextInvariantError("legal basis validity is invalid")


@dataclass(frozen=True)
class IngestionProvenance:
    originating_source: str
    originating_author: str
    ingested_at: datetime
    originally_recorded_at: datetime
    transformation_status: DeidentificationStatus
    policy_version: str
    source_reference_id: str
    def __post_init__(self):
        if any(not isinstance(value,str) or not value.strip() for value in (self.originating_source,self.originating_author,self.policy_version,self.source_reference_id)): raise InsufficientProvenance("complete ingestion provenance is required")
        if self.ingested_at.tzinfo is None or self.originally_recorded_at.tzinfo is None: raise InsufficientProvenance("provenance timestamps must be timezone-aware")


@dataclass(frozen=True)
class DeidentificationResult:
    fields: tuple[ClassifiedClinicalField, ...]
    status: DeidentificationStatus
    detected_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class ClinicalAccessAuditEvent:
    event_id: str
    event_type: ClinicalAuditEventType
    actor_id: str
    organization_id: str
    pseudonymous_patient_id: Optional[str]
    purpose: PurposeOfUse
    occurred_at: datetime
    policy_version: str
    outcome: str
    reason_code: str
    metadata_keys: tuple[str, ...] = ()
    def __post_init__(self):
        for value,name in ((self.event_id,"event_id"),(self.actor_id,"actor_id"),(self.organization_id,"organization_id"),(self.policy_version,"policy_version"),(self.outcome,"outcome"),(self.reason_code,"reason_code")): _required(value,name)
        if self.occurred_at.tzinfo is None: raise PatientContextInvariantError("audit timestamp must be timezone-aware")


@dataclass(frozen=True)
class IdentityMapping:
    identity_reference: str
    pseudonymous_patient_id: str
    created_at: datetime
    policy_version: str
    pseudonymization_key_id: str | None = None
    pseudonymization_key_version: str | None = None


@dataclass(frozen=True)
class AuthorizedClinicalIngestionRecord:
    """Metadata-only proof that the privacy boundary admitted one context version."""
    ingestion_record_id: str
    pseudonymous_patient_id: str
    patient_context_id: str
    patient_context_version: int
    source: str
    source_reference_id: str
    actor_reference: str
    organization_id: str
    tenant_id: str
    purpose: PurposeOfUse
    legal_basis_reference: str
    legal_basis_type: LegalBasisType
    authorization_decision_reference: str
    audit_event_reference: str
    classification_result: tuple[str, ...]
    deidentification_status: DeidentificationStatus
    detected_identifier_classes: tuple[str, ...]
    retained_field_names: tuple[str, ...]
    retention_policy_reference: str
    provenance_reference: str
    provenance_policy_version: str
    policy_versions: tuple[str, ...]
    recorded_at: datetime
    issued_at: datetime
    correlation_id: str
    integrity_hash: str

    def __post_init__(self):
        required = (
            self.ingestion_record_id, self.pseudonymous_patient_id,
            self.patient_context_id, self.source, self.source_reference_id,
            self.actor_reference, self.organization_id, self.tenant_id,
            self.legal_basis_reference, self.authorization_decision_reference,
            self.audit_event_reference,
            self.retention_policy_reference, self.provenance_reference,
            self.provenance_policy_version, self.correlation_id,
        )
        if any(not isinstance(value, str) or not value.strip() for value in required):
            raise InsufficientProvenance("complete authorized-ingestion metadata is required")
        if not self.pseudonymous_patient_id.startswith("pt_"):
            raise IdentityBoundaryViolation("canonical pseudonymous patient reference is required")
        if self.patient_context_version < 1 or not self.classification_result or not self.policy_versions:
            raise InsufficientProvenance("versioned governance metadata is required")
        if self.recorded_at.tzinfo is None or self.issued_at.tzinfo is None:
            raise InsufficientProvenance("ingestion record timestamps must be timezone-aware")
        if self.integrity_hash and len(self.integrity_hash) != 64:
            raise InsufficientProvenance("ingestion record integrity hash is invalid")


def authorized_ingestion_integrity_hash(record: AuthorizedClinicalIngestionRecord) -> str:
    material = asdict(record)
    material["integrity_hash"] = ""
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(encoded.encode("utf-8")).hexdigest()


def sign_authorized_ingestion_record(record: AuthorizedClinicalIngestionRecord) -> AuthorizedClinicalIngestionRecord:
    return replace(record, integrity_hash=authorized_ingestion_integrity_hash(record))


def validate_authorized_ingestion_record(record: AuthorizedClinicalIngestionRecord) -> bool:
    return bool(record.integrity_hash) and record.integrity_hash == authorized_ingestion_integrity_hash(record)
