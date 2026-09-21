# Patient Context Engine — MIP-01

## MIP-02 privacy and ingestion boundary

Patient Context accepts only canonical `pt_<HMAC-SHA256>` identifiers and contains no direct identity fields. Direct identity mapping is isolated behind an authorized port. The only supported write path is `ClinicalIngestionService`: typed command → registered source → authorization and legal-basis scope → explicit purpose → canonical classification → deterministic de-identification → purpose-based minimization → provenance → immutable context version. Public `PatientContextService` writes fail closed.

Unsafe free text is `REVIEW_REQUIRED` and cannot enter the context automatically. Retention is metadata, not destructive deletion. Access and denial events are append-only and exclude raw clinical values; PostgreSQL independently rejects audit `UPDATE` and `DELETE`. External KMS, SSO/OIDC and legal interpretation remain out of scope.

## Boundary

`jmoraIs.patient_context` is the canonical source of structured patient context for Phase 2. It represents clinician-supplied or source-derived facts and references only. It does not diagnose, interpret laboratory/imaging data, select guidelines, recommend treatment, predict outcomes, or invoke Scientific Core, RAG, LLM or embedding components.

## Architecture

- Domain: immutable traceable entities and the versioned `PatientContext` aggregate.
- Application: retrieval, append-only version creation and temporal timeline reconstruction.
- Ports: `PatientContextRepository`, owned by the bounded context.
- Adapters: append-only in-memory repository; PostgreSQL JSON document codec and repository prepared behind the same port.
- Schema: Alembic revision `009_patient_context`, with unique patient/version ordering, predecessor linkage and database-level UPDATE/DELETE rejection.

Every domain object records source, author, recorded date, confidence and provenance. Clinical events additionally require a canonical timeline ID and occurrence timestamp. Identity uses a pseudonymous platform patient ID; direct patient identifiers are not required by the aggregate.

## Versioning

Version 1 has no predecessor. Every update creates a new context ID, increments the version exactly once and references the current context ID. Historical versions remain retrievable and immutable. Timeline reconstruction merges referenced events deterministically and supports an `as-through-version` view.

## Safety

`DiagnosisCandidate` is a recorded candidate with `PROPOSED`, `UNDER_EVALUATION` or `RULED_OUT` status. It is not a diagnosis engine. Laboratory values are stored as reported strings with units/reference ranges; imaging stores modality, report reference and reported findings without interpretation.
## Stage-1 authorized-ingestion record

Every successful canonical ingestion now atomically persists a metadata-only
`AuthorizedClinicalIngestionRecord` alongside the minimized PatientContext version
and successful privacy-audit events. `ClinicalIngestionReceipt` is its
application-facing projection. Stage 1 therefore remains independently rereadable
after restart, while Stage 2 remains the sole clinical-context truth. See
`AUTHORIZED_CLINICAL_INGESTION_PERSISTENCE.md`.

## Exact persisted references

Patient Context alone issues `PersistedPatientContextReference` after proving that
the supplied immutable aggregate is identical to the canonical persisted version.
The metadata-only reference binds the exact context ID/version, pseudonymous
subject, tenant, policy, authorized-ingestion record and canonical content hash.
After restart, `get_exact(reference)` validates the persisted reference, RLS tenant,
policy, content integrity and predecessor continuity before returning the exact
aggregate. It never uses `latest()`, scans history or accepts free identity scalars.
Historical contexts without an owner-issued persisted reference remain legacy
readable but are ineligible for canonical FHIR incremental updates. See
`PATIENT_CONTEXT_EXACT_REFERENCE.md`.
