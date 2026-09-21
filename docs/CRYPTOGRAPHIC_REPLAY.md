# Cryptographic Ledger Replay — ST-21

## Offline production boundary

Global production replay is executed only by `OfflineReplayVerifier`. The API
runtime cannot provide global replay evidence because tenant RLS intentionally
hides other tenants. The verifier uses a separate KMS credential, pool and
`jmorais_offline_replay_verifier` role inside one read-only repeatable-read
snapshot. `PostgreSQLCryptographicReplayEngine` remains the canonical algorithm.

Every execution produces metadata-only append-only audit. `TAMPERED`, incomplete
visibility, unsafe grants, schema mismatch, unavailable secret, audit failure or
failed disposal blocks startup and release verification.

## Trust model

The PostgreSQL replay engine is read-only and distrusts stored integrity outcomes.
For each event it reconstructs the canonical payload, recomputes SHA-256, validates
the predecessor hash, position, identity, timestamp order, and domain references,
then compares the reconstructed head with an independent append-only checkpoint.

The replay decision is deliberately binary: `VALID` or `TAMPERED`. Any failed
event, missing checkpoint, broken position, invalid reference, hash mismatch, or
checkpoint mismatch makes its stream `TAMPERED`; any tampered stream makes the
overall report `TAMPERED`.

## Covered streams

- canonical Scientific Ledger events;
- governed clinical decision audit events;
- conflict adjudication events;
- GovernedEvidence lifecycle events;
- GovernedEvidence version history.
- GovernedLLMDraft lifecycle events, keyed by `tenant_id + draft_id`;
- LLM human-review decisions, keyed by `tenant_id + draft_id`;
- LLM human-review security events, keyed by `tenant_id + correlation_id`.
- PersistedGatewayInput trust records, keyed by
  `tenant_id + persisted_gateway_input_id`, one immutable record per stream.

The three Stage-13/14 families are mandatory. Global replay enumerates each
family explicitly and cannot return `VALID` when a family is unavailable,
unqueryable, cryptographically invalid, incomplete, or silently omitted.

## Completeness anchors

Migration `007_crypto_checkpoints` creates an append-only checkpoint stream.
PostgreSQL writes a checkpoint after every accepted historical insert. A checkpoint
records the stream namespace, stream identifier, expected position, head hash, and
timestamp. Existing history is deterministically backfilled during migration.

This separate anchor detects removal of the final event, which cannot be discovered
from a hash chain stored only inside the affected stream. Checkpoint `UPDATE` and
`DELETE` are rejected by the ST-20 database-level append-only function.

Migration `040_stage14_crypto_checkpoints` extends this same checkpoint stream;
it does not introduce another truth store. Its security-definer insert function
records tenant-qualified stream identities while existing checkpoint append-only
protections remain authoritative.

Migration `044_pgi_checkpoints` extends the registry without adding a second
checkpoint store. New PersistedGatewayInput records and their position-1 anchors
commit atomically through an `AFTER INSERT` trigger. Replay discovers this family
from the checkpoint registry, not solely from surviving trust rows. Consequently,
full deletion (the single-record equivalent of tail truncation), a missing anchor,
or head-hash divergence is `TAMPERED`. Pre-migration uncheckpointed records are
explicit legacy state and cannot contribute to a release-valid result.

## Stage-13/14 verification

Replay decodes the persisted canonical event payload and independently recomputes
the exact SHA-256 used by the owning bounded context. It verifies the duplicated
relational columns against that payload, genesis semantics, positions, predecessor
IDs, previous hashes, timestamp ordering, policy/tenant identity, and canonical
draft/invocation/request references. The engine does not re-execute review policy
or repair history.

The application reader/writer roles retain RLS and remain `NOBYPASSRLS`. Full
platform replay is an authorized integrity-verifier operation using the migration
owner/audit-verifier visibility; this does not grant broader access to application
repositories or API callers.

## Detection taxonomy

- `MODIFIED_PAYLOAD`
- `BROKEN_PREVIOUS_HASH`
- `BROKEN_STREAM_POSITION`
- `BROKEN_VERSION_CHAIN`
- `DUPLICATE_EVENT`
- `ROW_PAYLOAD_IDENTITY_MISMATCH`
- `INVALID_TIMESTAMP_ORDER`
- `INCONSISTENT_PROVENANCE_REFERENCES`
- `STREAM_COMPLETENESS_FAILURE`

## Report

`ReplayIntegrityReport` contains all stream reports, verified/failed totals, broken
chain count, integrity status, and overall decision. Each `StreamReplayReport`
contains the stream identity, verified event identifiers, structured failures,
broken chains, tampered event identifiers, and its binary status.

## Operational use

Replay should run after restart, before trusting reconstructed projections, during
release validation, and as a scheduled integrity control. A `TAMPERED` decision is
fail-closed and requires incident handling; replay never repairs, deletes, updates,
or silently accepts historical rows.

For the Stage-14 and `COMPLETE_CASE` release gates, global `VALID` means every
scientific, evidence, governed clinical, draft lifecycle, review decision, and
review security stream included by the canonical registry is `VALID`. There is no
partial-trust release state.
