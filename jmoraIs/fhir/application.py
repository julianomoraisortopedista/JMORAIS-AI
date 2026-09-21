from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from jmoraIs.patient_context.domain import RetentionMetadata
from jmoraIs.patient_context.ingestion import ClinicalIngestionCommand
from jmoraIs.patient_context.privacy import (ActorContext, AuthorizationRequest,
    DeidentificationStatus, IdentityMapping, IngestionProvenance, LegalBasis, PurposeOfUse)

from .domain import (FHIR_RELEASE, FhirDisposition, FhirIngestionResult,
    FhirSemanticError)


@dataclass(frozen=True)
class FhirImportCommand:
    payload: bytes
    identity_mapping: IdentityMapping
    actor: ActorContext
    purpose: PurposeOfUse
    authorization: AuthorizationRequest
    legal_basis: LegalBasis
    recorded_at: datetime
    retention: RetentionMetadata
    fhir_version: str = FHIR_RELEASE
    previous_context_reference: object | None = None

    def __post_init__(self):
        if not isinstance(self.payload,bytes): raise TypeError("FHIR payload must be bytes")
        if not isinstance(self.identity_mapping,IdentityMapping): raise TypeError("trusted identity mapping is required")
        if self.recorded_at.tzinfo is None: raise FhirSemanticError("recorded_at must be timezone-aware")


class FhirIngestionService:
    def __init__(self,parser,mapper,clinical_ingestion,contexts,exact_references,idempotency):
        self._parser=parser;self._mapper=mapper;self._clinical_ingestion=clinical_ingestion
        self._contexts=contexts;self._exact=exact_references;self._idempotency=idempotency

    def import_bundle(self,command:FhirImportCommand)->FhirIngestionResult:
        if not isinstance(command,FhirImportCommand): raise TypeError("typed FHIR import command is required")
        bundle=self._parser.parse(command.payload,fhir_version=command.fhir_version)
        self._validate_identity(bundle,command.identity_mapping)
        previous=None
        if command.previous_context_reference is not None:
            previous=self._exact.get_exact(command.previous_context_reference)
            if previous.patient_identity.patient_id!=command.identity_mapping.pseudonymous_patient_id:
                raise FhirSemanticError("incremental PatientContext subject mismatch")
        source=self._mapper._source(bundle,previous)
        existing=self._idempotency.find(source)
        if existing is not None:
            self._exact.get_exact(existing)
            return FhirIngestionResult(FhirDisposition.IDEMPOTENT_REDELIVERY,existing,None)
        mapped=self._mapper.map(bundle,command.identity_mapping,recorded_at=command.recorded_at,
            retention=command.retention,previous=previous)
        if mapped.review_reasons:
            return FhirIngestionResult(FhirDisposition.REVIEW_REQUIRED,None,None,mapped.review_reasons)
        ingestion=ClinicalIngestionCommand(mapped.context,command.identity_mapping.identity_reference,
            command.actor,"FHIR_R4",command.recorded_at,command.purpose,command.authorization,
            command.legal_basis,mapped.clinical_payload,IngestionProvenance("FHIR_R4",
            command.actor.actor_id,command.recorded_at,command.recorded_at,
            DeidentificationStatus.NOT_REQUIRED,self._mapper._policy,mapped.source_reference_id),1)
        receipt=self._clinical_ingestion.ingest(ingestion)
        persisted=self._contexts.get(receipt.context_id)
        if persisted is None: raise FhirSemanticError("canonical PatientContext persistence is unavailable")
        reference=self._exact.reference_for(persisted)
        record=getattr(self._idempotency,"record",None)
        if record is not None: record(mapped.source_reference_id,reference)
        return FhirIngestionResult(FhirDisposition.INGESTED,reference,receipt.ingestion_record_id)

    @staticmethod
    def _validate_identity(bundle,mapping):
        patients=tuple(item for item in bundle.resources if item.resource_type=="Patient")
        if len(patients)!=1: raise FhirSemanticError("Bundle must contain exactly one Patient")
        patient=patients[0]
        identifiers=patient.data.get("identifier",())
        expected={f"fhir:{item.get('system')}|{item.get('value')}" for item in identifiers
            if item.get("system") and item.get("value")}
        if not expected or mapping.identity_reference not in expected:
            raise FhirSemanticError("FHIR Patient identity mapping mismatch")
