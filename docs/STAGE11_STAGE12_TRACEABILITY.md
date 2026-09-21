# Stage 11 → Stage 12 Traceability

## Architectural decision

Medical Document and Audit Defense remain separate bounded contexts. Audit Defense
does not derive its reasoning from document prose, so this relationship is a
workflow trace link, not a clinical or scientific input dependency.

After a `DefensePackage` is generated from its existing governed inputs,
`AuditDefenseTraceabilityService` resolves an exact persisted
`MedicalDocumentVersion` through `MedicalDocumentTracePort` and appends a new
package version containing `MedicalDocumentVersionReference`. The reference holds
only document stream, document ID, exact version, tenant, canonical serialization
hash and policy version. No section, narrative, citation or clinical payload is
copied.

## Source of truth and exact-version semantics

`PostgreSQLMedicalDocumentTraceAdapter` reads the canonical Medical Document
repository under the active tenant context. It filters the complete persisted
history by the requested exact version and requires exactly one match; `latest()`
is never used. The adapter computes the reference integrity value with the
canonical `MedicalDocumentJsonCodec` and revalidates identity, policy, tenant and
integrity whenever the backward trace resolves the reference.

The traceability service accepts no caller-provided document ID/version pair. It
accepts only a typed reference already issued by this repository-backed adapter
and resolves that reference again before append. Missing, forged, ambiguous,
cross-tenant or integrity-mismatched references fail closed.

## Persistence, tenancy and restart

Migration `042_stage11_stage12_traceability` adds nullable reference columns to
the existing append-only `audit_defense_versions` history. Older package versions
remain valid historical records; a linkage is introduced only by appending a new
version. The existing RLS policy and runtime `NOBYPASSRLS` roles remain the tenant
boundary. A composite foreign key binds stream/version to the canonical Medical
Document history, while repository reread compares indexed columns with the
encoded immutable package payload.

After restart, the DefensePackage repository reconstructs the reference and the
trace adapter resolves the exact document version without cache or process-local
state. Review transitions carry the reference forward; they never rewrite it.

## Replay and integrity

Audit Defense package rows are protected by append-only PostgreSQL triggers but
are not currently registered as cryptographic event streams in
`PostgreSQLCryptographicReplayEngine`. The new reference therefore does not alter
an existing replay hash contract. It is included in the immutable package JSON,
mirrored in constrained columns and checked for column/payload consistency on
reread. Cryptographic replay coverage for Audit Defense version history remains a
separate platform-wide enhancement; this change does not silently exclude a field
from an existing cryptographic stream.

## Backward-trace role

The canonical traversal is:

```text
DefensePackage
→ MedicalDocumentVersionReference
→ MedicalDocumentRepository exact history lookup
→ MedicalDocumentVersion
```

This link proves that both artifacts belong to the same governed workflow. It
does not assert that Audit Defense reasoning was derived from document prose.
