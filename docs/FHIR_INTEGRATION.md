# FHIR Integration — Sprint S001

## Boundary

`jmoraIs.fhir` is an inbound interoperability adapter for HL7 FHIR R4 `4.0.1`.
FHIR is never a clinical source of truth and no FHIR model crosses into a frozen
clinical bounded context.

The canonical flow is:

`FHIR bytes → structural validation → local reference resolution → deterministic
mapping → ClinicalIngestionService → PatientContext → owner-issued exact reference`.

The adapter supports `collection`, `transaction`, `batch` and `document` Bundles as
local ingestion containers. It does not execute transaction/batch operations against
an external FHIR server and performs no network reference resolution.

## Supported resources

The MVP accepts only Patient, Practitioner, Organization, Encounter, Condition,
Observation, Procedure, MedicationStatement, AllergyIntolerance, DiagnosticReport,
DocumentReference, ImagingStudy, Coverage and CarePlan. Every other resource fails
explicitly with `UNSUPPORTED_RESOURCE`.

## Canonical ingestion

Patient direct identifiers remain transient and are passed as classified direct
identifier fields to the established authorization, de-identification and
minimization pipeline. The adapter cannot append PatientContext directly.
PatientContext persistence, authorized-ingestion evidence and exact-reference
issuance remain owned by Patient Context.

Incremental ingestion requires `PersistedPatientContextReference`. The exact prior
aggregate is resolved through `get_exact(reference)` after restart, mapped into a
new immutable version and admitted through the same governed ingestion service.
There is no `latest()`, history scan or scalar reconstruction in the FHIR boundary.

## Idempotency

Source identity binds FHIR release, Bundle ID, exact payload hash, mapping-policy
version and prior exact context identity. The PostgreSQL adapter projects existing
canonical authorized-ingestion and exact-reference metadata; it creates no second
FHIR clinical database and stores no raw resource. Redelivery returns the existing
owner-issued reference only after canonical exact validation.
