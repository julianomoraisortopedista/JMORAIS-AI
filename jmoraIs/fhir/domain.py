from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Mapping


FHIR_RELEASE = "4.0.1"
SUPPORTED_RESOURCES = frozenset({
    "Patient", "Practitioner", "Organization", "Encounter", "Condition",
    "Observation", "Procedure", "MedicationStatement", "AllergyIntolerance",
    "DiagnosticReport", "DocumentReference", "ImagingStudy", "Coverage", "CarePlan",
})
SUPPORTED_BUNDLE_TYPES = frozenset({"collection", "transaction", "batch", "document"})


class FhirBoundaryError(RuntimeError): pass
class FhirStructuralError(FhirBoundaryError): pass
class FhirSemanticError(FhirBoundaryError): pass
class UnsupportedFhirResource(FhirBoundaryError): pass
class FhirReferenceError(FhirBoundaryError): pass
class FhirSecurityError(FhirBoundaryError): pass
class FhirConflictError(FhirBoundaryError): pass


class FhirDisposition(str, Enum):
    INGESTED = "INGESTED"
    IDEMPOTENT_REDELIVERY = "IDEMPOTENT_REDELIVERY"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


@dataclass(frozen=True)
class FhirLimits:
    max_bundle_bytes: int = 1_000_000
    max_resources: int = 100
    max_reference_depth: int = 8
    max_nesting_depth: int = 24
    max_document_metadata_chars: int = 4_096
    max_diagnostic_results: int = 100
    max_observation_components: int = 50


@dataclass(frozen=True)
class FhirResource:
    resource_type: str
    resource_id: str
    full_url: str | None
    version_id: str | None
    last_updated: datetime | None
    data: Mapping[str, Any]

    @property
    def logical_reference(self) -> str:
        return f"{self.resource_type}/{self.resource_id}"


@dataclass(frozen=True)
class FhirBundle:
    bundle_id: str
    bundle_type: str
    fhir_version: str
    resources: tuple[FhirResource, ...]
    content_hash: str


@dataclass(frozen=True)
class FhirCodeDecision:
    accepted: bool
    review_required: bool
    display: str | None
    provenance: tuple[str, ...]


@dataclass(frozen=True)
class FhirMappingResult:
    context: object | None
    clinical_payload: tuple[object, ...]
    source_reference_id: str
    review_reasons: tuple[str, ...]
    mapped_resource_references: tuple[str, ...]


@dataclass(frozen=True)
class FhirIngestionResult:
    disposition: FhirDisposition
    patient_context_reference: object | None
    authorized_ingestion_record_id: str | None
    review_reasons: tuple[str, ...] = ()
