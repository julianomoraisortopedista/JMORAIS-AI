# Governed LLM Draft Exact Persisted Reference

`PersistedGovernedLLMDraftReference` is the Governed LLM Draft owner-issued,
metadata-only trust input for the future S003 LLM Trace Viewer. Compatibility
queries by `draft_id`, stream history, or latest version remain internal legacy
paths and cannot establish Workspace trust.

`reference_for()` first proves that the supplied immutable draft is byte-for-byte
equivalent to canonical PostgreSQL persistence. It validates the real stream
version and predecessor chain, draft signature and content hash, current lifecycle,
exact LLM invocation, persisted Gateway input, upstream artifact, tenant, policy,
correlation, and provenance. Only an `ACTIVE` draft can receive a reference.
Issuance now requires a typed, owner-issued `PersistedLLMInvocationReference` and
resolves it through the Gateway exact query port before binding it to the draft.

`get_exact()` accepts only the persisted owner-issued reference. It repeats every
validation after restart and rejects missing, forged, superseded, invalidated,
cross-tenant, or inconsistent artifacts. It never calls `latest()` or `history()`
and never accepts free identity/version scalars.
The linked invocation reference is itself reread and validated; a scalar
`invocation_id` alone no longer qualifies for S003 trust.

The reference table contains trust metadata only. It does not contain reviewable
content, prompts, provider payloads, raw responses, or clinical payloads. The table
is append-only, tenant-scoped, protected by PostgreSQL RLS, and covered by an
independent cryptographic completeness checkpoint. Offline Replay recomputes the
reference integrity hash and detects either row or checkpoint deletion.

Drafts without an owner-issued reference remain available through compatibility
contracts but are classified as
`LEGACY_MISSING_PERSISTED_GOVERNED_LLM_DRAFT_REFERENCE` and are not eligible as
canonical S003 LLM Trace Viewer inputs.
Draft references created before the typed invocation link remain immutable and are
classified as `LEGACY_MISSING_PERSISTED_LLM_INVOCATION_REFERENCE` by the new exact
path; no synthetic backfill is performed.
