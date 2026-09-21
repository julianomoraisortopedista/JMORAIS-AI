# Authorized Clinical Ingestion Persistence

## Purpose

`AuthorizedClinicalIngestionRecord` is the canonical Stage-1 proof that one typed
clinical ingestion passed authorization, purpose/legal-basis, classification,
de-identification, minimization, provenance and retention controls. It is distinct
from Stage 2, `PatientContext`, and contains governance metadata and opaque
references only.

The application-facing `ClinicalIngestionReceipt` is a projection of this durable
record. Its `ingestion_record_id` provides the exact restart-safe query identity;
it is not a second source of truth.

## Atomic transaction

`ClinicalIngestionService` remains the only canonical write boundary. Successful
ingestion calls `AuthorizedClinicalIngestionRepository.append_atomic()` once. The
PostgreSQL adapter commits these artifacts in one transaction:

```text
minimized PatientContext version
+ AuthorizedClinicalIngestionRecord
+ successful privacy-audit events
```

There is no post-ingestion receipt write and no second PatientContext append. Any
failure rolls back all three artifact families. Denials and pre-success failures
retain their existing fail-closed audit behavior without creating a success record.

## Privacy and integrity

The Stage-1 record contains no clinical payload, raw document, free text, direct
identity, token, credential or secret. It retains the pseudonymous patient
reference, exact context ID/version, opaque actor/source/legal-basis/authorization
references, classification categories, de-identification/minimization outcome,
retention/provenance references, policies, tenant/correlation and timestamps.

SHA-256 covers the complete canonical record representation. Reads recompute the
hash, compare duplicated relational columns with the JSON document, and join the
exact referenced PatientContext ID/version. Forged payloads, changed columns,
missing contexts and wrong versions fail closed.

## PostgreSQL and tenancy

Migration `041_authorized_ingestion_records` creates the append-only tenant-scoped
history. RLS derives access from transaction-local tenant context. Application
reader/writer roles remain `NOBYPASSRLS`; wrong-tenant queries return no record and
missing context is rejected by the query port. Runtime roles have no `UPDATE`,
`DELETE` or `TRUNCATE` authority, and the immutable-history trigger independently
rejects destructive mutation.

## Restart and E2E handoff

After process disposal, `AuthorizedClinicalIngestionQueryPort.get()` reconstructs
Stage 1. Its exact PatientContext reference is then resolved through
`PatientContextRepository.get()` for Stage 2. The validation-only adapters
`AuthorizedIngestionPersistenceAdapter` and `PatientContextRereadStageAdapter`
verify this boundary without persisting either artifact a second time.
