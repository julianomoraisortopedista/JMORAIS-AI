# Patient Context Exact Persisted Reference

## Purpose

`PersistedPatientContextReference` is the owner-issued, restart-safe trust contract
for resolving one exact persisted `PatientContext`. It prepares Sprint S001 for
incremental FHIR updates without implementing FHIR or changing Patient Context,
privacy, ingestion or minimization semantics.

## Canonical flow

`PatientContext persisted → reference_for(context) → persisted reference →
runtime disposal → fresh PostgreSQL composition → get_exact(reference) →
exact PatientContext`.

Patient Context is the sole issuer. `reference_for()` first compares the supplied
aggregate with the canonical PostgreSQL row. It then persists only opaque identity,
version, pseudonymous subject, tenant, policy, authorized-ingestion linkage,
canonical content hash, reference integrity hash and issuance time.

## Exact resolution

`get_exact()` accepts only the immutable typed reference. It validates:

- the reference's self-integrity and persisted equality;
- transaction-local tenant context and PostgreSQL RLS;
- exact context ID, version and pseudonymous subject;
- policy and authorized-ingestion linkage;
- canonical context payload hash without duplicating that payload;
- immediate predecessor/version continuity when applicable.

Resolution never calls `latest()`, scans history or trusts caller-provided scalar
identity. The application runtime role remains `NOBYPASSRLS`.

## Privacy and persistence

`patient_context_persisted_references` is append-only, immutable and RLS protected.
It stores no direct identifier, raw clinical text, source document, FHIR payload,
email, phone or national identifier. Patient Context remains the clinical source of
truth; the reference table is metadata-only trust evidence.

## Legacy policy

Existing contexts without an owner-issued persisted reference remain accessible
through established legacy query contracts. They are explicitly ineligible for the
canonical incremental FHIR flow and are classified as
`LEGACY_MISSING_PERSISTED_PATIENT_CONTEXT_REFERENCE`. No reference is fabricated
from an ID, version, latest row or history scan.

## Scope

This prerequisite exposes only
`PersistedPatientContextReference → get_exact(reference) → PatientContext`.
FHIR resources, parsing, mapping and orchestration remain outside this increment.
