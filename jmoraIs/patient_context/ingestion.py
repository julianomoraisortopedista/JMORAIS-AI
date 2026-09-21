from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from uuid import uuid4

from .application import PatientContextNotFound, PatientContextVersionConflict
from .domain import PatientContext, Sex
from .ports import PatientContextRepository
from .privacy import (
    ActorContext, AuthorizationRequest, ClinicalAccessAuditEvent, ClinicalAuditEventType,
    ClinicalAuthorizationDenied, ClassifiedClinicalField, DeidentificationRequired,
    DirectIdentifierDetected, IngestionProvenance, InsufficientProvenance,
    InvalidClinicalSource, LegalBasis, PurposeNotAllowed, PurposeOfUse,
    AuthorizedClinicalIngestionRecord, sign_authorized_ingestion_record,
)
from .privacy_ports import (ClinicalAccessAuditRepository, ClinicalDataAuthorizationPort,
    DataMinimizationPort, DeidentificationPort, PatientIdentityMappingPort,
    AuthorizedClinicalIngestionRepository)
from jmoraIs.tenancy.context import current_tenant_context


@dataclass(frozen=True)
class ClinicalIngestionCommand:
    context: PatientContext
    identity_lookup_reference: str | None
    actor: ActorContext
    source: str
    recorded_at: datetime
    purpose: PurposeOfUse
    authorization: AuthorizationRequest
    legal_basis: LegalBasis
    clinical_payload: tuple[ClassifiedClinicalField, ...]
    provenance: IngestionProvenance
    schema_version: int
    def __post_init__(self):
        if not isinstance(self.context,PatientContext): raise TypeError("typed PatientContext is required")
        if not isinstance(self.purpose,PurposeOfUse): raise PurposeNotAllowed("purpose is required")
        if not isinstance(self.clinical_payload,tuple) or not all(isinstance(item,ClassifiedClinicalField) for item in self.clinical_payload): raise TypeError("typed clinical payload is required")


@dataclass(frozen=True)
class ClinicalIngestionReceipt:
    ingestion_record_id: str
    context_id: str
    patient_id: str
    version: int
    authorization_decision_id: str
    retained_field_names: tuple[str, ...]
    deidentification_status: str
    audit_event_id: str

    @classmethod
    def from_record(cls, record: AuthorizedClinicalIngestionRecord):
        return cls(record.ingestion_record_id, record.patient_context_id,
            record.pseudonymous_patient_id, record.patient_context_version,
            record.authorization_decision_reference, record.retained_field_names,
            record.deidentification_status.value, record.audit_event_reference)

@dataclass(frozen=True)
class ClinicalContextAccessRequest:
    actor: ActorContext; patient_id: str; purpose: PurposeOfUse
    authorization: AuthorizationRequest; legal_basis: LegalBasis

class AuthorizedPatientContextAccessService:
    def __init__(self,repository,authorization,audit,*,clock):
        self._repository=repository;self._authorization=authorization;self._audit=audit;self._clock=clock
    def retrieve(self,request):
        decision=self._authorization.authorize(request.authorization,request.legal_basis)
        allowed=(decision.allowed and request.authorization.patient_scope==request.patient_id
          and request.legal_basis.patient_scope==request.patient_id and request.authorization.purpose==request.purpose
          and request.purpose in request.legal_basis.purposes)
        event=ClinicalAccessAuditEvent(str(uuid4()),ClinicalAuditEventType.CONTEXT_ACCESS,request.actor.actor_id,
          request.actor.organization_id,request.patient_id,request.purpose,self._clock(),request.authorization.policy_version,
          "ALLOWED" if allowed else "DENIED","AUTHORIZED" if allowed else "POLICY_DENIED",("context_id",))
        self._audit.append(event)
        if not allowed: raise ClinicalAuthorizationDenied("patient context access denied")
        context=self._repository.latest(request.patient_id)
        if context is None: raise PatientContextNotFound("patient context does not exist")
        return context


class ClinicalIngestionService:
    """The only application service authorized to append Patient Context."""
    def __init__(self, repository: PatientContextRepository, authorization: ClinicalDataAuthorizationPort,
                 identities: PatientIdentityMappingPort, deidentifier: DeidentificationPort,
                 minimizer: DataMinimizationPort, audit: ClinicalAccessAuditRepository,
                 ingestion_records: AuthorizedClinicalIngestionRepository,
                 *, allowed_sources: tuple[str,...], clock):
        self._repository=repository;self._authorization=authorization;self._identities=identities
        self._deidentifier=deidentifier;self._minimizer=minimizer;self._audit=audit
        self._ingestion_records=ingestion_records
        self._allowed_sources=frozenset(allowed_sources);self._clock=clock

    def ingest(self, command: ClinicalIngestionCommand) -> ClinicalIngestionReceipt:
        patient_id=command.context.patient_identity.patient_id
        self._validate_envelope(command)
        decision=self._authorization.authorize(command.authorization,command.legal_basis)
        if not decision.allowed:
            self._emit(command,ClinicalAuditEventType.AUTHORIZATION_DENIAL,"DENIED",decision.reason_code)
            raise ClinicalAuthorizationDenied(decision.reason_code)
        if command.authorization.patient_scope != patient_id or command.legal_basis.patient_scope != patient_id:
            self._emit(command,ClinicalAuditEventType.PURPOSE_MISMATCH,"DENIED","PATIENT_SCOPE_MISMATCH")
            raise PurposeNotAllowed("patient scope does not match the ingestion target")
        if command.purpose not in command.legal_basis.purposes or command.authorization.purpose != command.purpose:
            self._emit(command,ClinicalAuditEventType.PURPOSE_MISMATCH,"DENIED","PURPOSE_MISMATCH")
            raise PurposeNotAllowed("purpose is outside the authorized legal-basis scope")
        success_events=[]
        if command.identity_lookup_reference:
            mapping=self._identities.resolve(command.identity_lookup_reference,decision)
            if mapping is None or mapping.pseudonymous_patient_id != patient_id:
                self._emit(command,ClinicalAuditEventType.IDENTITY_LOOKUP,"DENIED","IDENTITY_MAPPING_MISMATCH")
                raise ClinicalAuthorizationDenied("identity mapping does not match patient scope")
            success_events.append(self._event(command,ClinicalAuditEventType.IDENTITY_LOOKUP,"ALLOWED","AUTHORIZED_LOOKUP"))
        deidentified=self._deidentifier.transform(command.clinical_payload,patient_id)
        if deidentified.status.value == "REVIEW_REQUIRED":
            self._emit(command,ClinicalAuditEventType.DEIDENTIFICATION_FAILURE,"BLOCKED","REVIEW_REQUIRED")
            raise DeidentificationRequired("unsafe free text requires deterministic human review")
        if any(item.classification.data_class.value == "DIRECT_IDENTIFIER" for item in deidentified.fields):
            raise DirectIdentifierDetected("direct identifiers may not enter Patient Context")
        retained=self._minimizer.minimize(deidentified.fields,command.purpose)
        minimized_context=self._minimize_context(command.context,{item.name for item in retained})
        self._validate_append(minimized_context)
        audit=self._event(command,ClinicalAuditEventType.INGESTION,"ALLOWED","INGESTED",tuple(item.name for item in retained))
        success_events.append(audit)
        tenant=current_tenant_context()
        unsigned=AuthorizedClinicalIngestionRecord(
            "ingestion_"+uuid4().hex,patient_id,minimized_context.context_id,minimized_context.version,
            command.source,command.provenance.source_reference_id,command.actor.actor_id,
            command.actor.organization_id,tenant.tenant_id,command.purpose,command.legal_basis.basis_id,
            command.legal_basis.basis_type,decision.decision_id,audit.event_id,
            tuple(sorted({item.classification.data_class.value for item in command.clinical_payload})),
            deidentified.status,tuple(sorted({item.classification.data_class.value for item in command.clinical_payload
                if item.name in deidentified.detected_fields})),tuple(item.name for item in retained),
            minimized_context.retention.policy_id,command.provenance.source_reference_id,
            command.provenance.policy_version,tuple(dict.fromkeys((decision.policy_version,
                command.legal_basis.policy_version,command.provenance.policy_version))),command.recorded_at,
            self._clock(),tenant.correlation_id,"")
        record=sign_authorized_ingestion_record(unsigned)
        self._ingestion_records.append_atomic(minimized_context,record,tuple(success_events))
        return ClinicalIngestionReceipt.from_record(record)

    @staticmethod
    def _minimize_context(context, retained):
        optional_scalars=("age_years","weight_kg","height_cm","bmi","dominant_side","athlete_status","smoking","alcohol",
          "physical_activity","pregnancy","performance_status")
        collections=("clinical_problems","diagnosis_candidates","findings","comorbidities","medical_history_items",
          "medication_classes","medications","allergies","procedures","implants","laboratory_results","imaging_studies",
          "vital_signs","functional_statuses","pain_assessments","risk_factors","lifestyle_factors","occupations",
          "sports_activities","follow_up_plans","encounters","clinical_note_references","current_conditions","orthopedic_contexts")
        changes={name:None for name in optional_scalars if name not in retained}
        changes.update({name:() for name in collections if name not in retained})
        if "sex" not in retained: changes["sex"]=Sex.NOT_REPORTED
        return replace(context,**changes)

    def _validate_envelope(self, command):
        if command.source not in self._allowed_sources: raise InvalidClinicalSource("clinical source is not registered")
        if command.schema_version < 1: raise InsufficientProvenance("schema version is required")
        if command.recorded_at.tzinfo is None: raise InsufficientProvenance("recorded_at must be timezone-aware")
        if not command.provenance.source_reference_id or command.provenance.originating_source != command.source: raise InsufficientProvenance("complete source provenance is required")
        if command.authorization.purpose != command.purpose: raise PurposeNotAllowed("authorization purpose mismatch")
        requested={item.classification.data_class for item in command.clinical_payload}
        if not requested.issubset(set(command.authorization.requested_classes)): raise ClinicalAuthorizationDenied("payload classes exceed authorization request")

    def _validate_append(self, context):
        current=self._repository.latest(context.patient_identity.patient_id)
        if current is None:
            if context.version!=1 or context.previous_context_id is not None: raise PatientContextVersionConflict("new context must start at version 1")
        elif context.context_id==current.context_id or context.version!=current.version+1 or context.previous_context_id!=current.context_id:
            raise PatientContextVersionConflict("ingestion must append the next immutable version")

    def _emit(self, command, kind, outcome, reason, keys=()):
        event=self._event(command,kind,outcome,reason,keys)
        self._audit.append(event);return event

    def _event(self, command, kind, outcome, reason, keys=()):
        return ClinicalAccessAuditEvent(str(uuid4()),kind,command.actor.actor_id,command.actor.organization_id,
            command.context.patient_identity.patient_id,command.purpose,self._clock(),command.authorization.policy_version,
            outcome,reason,tuple(keys))
