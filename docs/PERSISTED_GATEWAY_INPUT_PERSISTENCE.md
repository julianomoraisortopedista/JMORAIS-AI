# Persisted Gateway Input Persistence

## Purpose

`PersistedGatewayInputRecord` is the canonical restart-safe proof that a review-eligible LLM invocation used an owner-issued DTO projection of one exact persisted upstream artifact. It is a trust record, not a clinical content store.

## Stored data

The PostgreSQL record contains only opaque identity and governance metadata: canonical record ID, tenant, upstream artifact type/ID/version, owner context and integrity reference, policy, DTO hash, issuance time, original HMAC signature, managed signing-key reference/version and record integrity hash. Request and invocation lookup is supplied by the invocation foreign-key relationship.

It never contains the DTO, document sections, audit-defense arguments, reasoning input, prompt, provider response, generated text, direct identity, credentials or secrets.

## Restart verification

The canonical trust service performs a fail-closed sequence:

1. reread the tenant-visible trust record and validate relational fields against its canonical payload and integrity hash;
2. resolve the exact owner artifact type, ID and version through the owning repository-backed resolver;
3. project the canonical DTO and recompute its SHA-256 hash;
4. obtain the referenced signing key through the managed Secrets/KMS boundary;
5. verify the original HMAC without regenerating or replacing it.

No `latest()` lookup, cache, inferred version, raw-secret persistence or DTO duplication is allowed.

Audit Defense owns `AuditDefenseGatewayInputResolver`. It rereads one exact
`DefensePackage` version, validates tenant, policy and canonical package integrity,
and resolves the embedded Stage-11 `MedicalDocumentVersionReference` through the
Medical Document authority before returning the canonical `AuditDefense` DTO. The
generic trust service then recomputes the DTO hash and verifies the original HMAC.
The LLM Gateway imports neither the owner repository nor this resolver.

Scalar identity selection is insufficient for the governed path because it makes
the caller choose the trusted owner version. The canonical forward handoff is the
typed final `DefensePackage` returned by an exact repository reread. The issuer
independently verifies that same row and derives artifact ID/version, tenant, policy,
integrity and DTO projection. Reverse resolution follows the persisted record back
through the identical package and Stage-11 document reference after restart.

## PostgreSQL controls

Migration `043_persisted_gateway_inputs` creates the tenant-scoped append-only table, indexes, integrity constraints, forced Row-Level Security and the invocation foreign key. Runtime reader/writer roles remain `NOBYPASSRLS`; missing tenant context and cross-tenant reads fail closed. UPDATE and DELETE are rejected.

Historical invocations without a canonical input ID remain queryable as `LEGACY_MISSING_PERSISTED_GATEWAY_INPUT`; no historical attestation is fabricated and these rows are ineligible for final COMPLETE_CASE evidence.

## Replay and E2E role

Row integrity alone cannot detect deletion of the row that carries that integrity value. Migration `044_pgi_checkpoints` therefore adds an independent completeness anchor using the existing `cryptographic_stream_checkpoints` registry. Each trust record is one immutable stream identified as `tenant_id|persisted_gateway_input_id`, with position/count `1` and `record_integrity_hash` as its head.

An `AFTER INSERT` PostgreSQL trigger writes the record and checkpoint in the same transaction. A checkpoint conflict rolls back the record insert; a rejected record creates no checkpoint. Historical rows are deliberately not backfilled because no independent proof existed when they were accepted. They are `LEGACY_UNCHECKPOINTED_PERSISTED_GATEWAY_INPUT` and cannot qualify for release evidence.

Global replay discovers expected records from checkpoints as well as surviving rows. A missing record, missing checkpoint, count/hash divergence, malformed stream identity or linkage mismatch produces `TAMPERED`. Because each identity is a single-record stream, full-record deletion is its tail-truncation case; intermediate deletion is not meaningful for this family.

The global PostgreSQL replay engine includes this release-critical stream and validates completeness, record integrity and invocation linkage. The focused restart proof establishes:

`LLMInvocation → PersistedGatewayInputRecord → exact MedicalDocumentVersion`.

The full COMPLETE_CASE 1→14 remains a separate acceptance run.
