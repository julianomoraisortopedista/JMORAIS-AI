# Human Review Exact Persisted Reference

`PersistedHumanReviewReference` is the Human Review owner-issued, metadata-only
trust reference for the S003 Human Review Viewer.

Issuance requires the exact persisted `LLMHumanReviewEvent`, its valid hash chain,
and a typed `PersistedGovernedLLMDraftReference` resolved through the draft owner.
Exact reread reconstructs both persisted references after restart and returns the
historical event itself; it does not use `current_state()`, `history()`, or free
draft/version scalars.

The reference contains no draft content, clinical payload, prompt, model response,
JWT/JTI, or secret. Its PostgreSQL table is append-only, RLS-protected and included
in cryptographic replay completeness. Existing review events without an owner-issued
reference remain immutable legacy records and are not eligible for S003 trust.
