# Governed LLM Draft Lifecycle

## Purpose and states

Lifecycle is an immutable event stream owned by `jmoraIs.governed_llm_draft`. It answers whether an exact persisted draft version is `ACTIVE`, `SUPERSEDED`, or `INVALIDATED` without changing or deleting the draft. Human Review consumes this status later but is not implemented here.

Allowed transitions are genesis `None → ACTIVE`, followed only by `ACTIVE → SUPERSEDED` or `ACTIVE → INVALIDATED`. Reactivation and transitions from terminal states fail closed.

## Atomic genesis and supersession

Canonical issuance uses `append_with_lifecycle()`. Draft insertion and its genesis `ACTIVE` event share one PostgreSQL transaction. A new version atomically inserts its own genesis and appends `SUPERSEDED` to the prior active version, including `REPLACED_BY:<draft_id>`. A failure rolls back all writes, so no canonical draft can exist with unknowable lifecycle.

Draft version and lifecycle are distinct. Old rows remain immutable and readable even after lifecycle supersession. `current_active(stream_id)` derives authority exclusively from verified lifecycle events, never from the numerically latest draft.

Migration `037_backfill_draft_lifecycle` handles drafts issued before lifecycle deployment by writing deterministic genesis events and supersession links. Runtime code never guesses legacy state.

## Integrity, persistence and isolation

Each event records exact draft ID/version, tenant, prior/resulting status, reason, actor, policy, timestamp, stream position, predecessor event and previous hash. SHA-256 is recomputed across canonical event fields during every history/status query. Missing positions, altered payloads, broken predecessors or hashes fail closed.

PostgreSQL uses advisory locks, unique tenant/draft/position, append-only triggers and tenant RLS. Runtime writer can append; runtime reader is read-only; both remain `NOBYPASSRLS`. Wrong-tenant and missing-context queries reveal no lifecycle.

After restart, `draft_id + version → verified lifecycle history → current status` reconstructs the same result. Stage 14 must require `ACTIVE` and must never infer eligibility from draft version history.
# Review-time enforcement

Stage 14 requires an explicit lifecycle query and permits only `ACTIVE`. The review repository locks the lifecycle stream and rechecks its state in the same transaction that appends the review decision, preventing stale approval after supersession or invalidation.
