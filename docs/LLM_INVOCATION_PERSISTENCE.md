# LLM Invocation Persistence

`LLMInvocation` is the immutable operational record of an attempted canonical Gateway
request. For completed responses it preserves the exact `LLMOutputClassification`; it
never reconstructs classification from `InvocationStatus`. This distinction is required
because both `APPROVED_FOR_REVIEW` and `REVIEW_REQUIRED` are successful invocations.

The invocation also preserves the actual `temperature` and `seed` supplied by the
validated `LLMRequest`. Provider output does not create or alter generation
configuration. `PromptAudit` intentionally records the same two values for its separate
audit purpose, and PostgreSQL rejects request-scoped audit persistence when invocation
and audit configuration differ.

Only operational metadata is stored: identities, hashes, provider/model references,
classification, generation parameters, usage, cost, latency, status, policy, correlation
and timestamp. Raw prompt text, canonical DTO payload, clinical content and raw provider
response are absent from invocation persistence.

Migration `031_llm_invocation_metadata` leaves historical rows nullable and unchanged.
Rows missing classification or generation configuration are
`LEGACY_INCOMPLETE_INVOCATION_METADATA`: immutable and request-queryable, but ineligible
as restart-equivalent Stage-13 evidence. Newly governed completed invocations require a
classification and valid temperature; provider failures retain a null classification
because no canonical output classification was produced.

Tenant scope and RLS remain independent of invocation metadata. Restart reconstruction
reads the exact JSONB record and never joins PromptAudit to infer missing values.

New canonical invocations require a persisted trusted invocation context with matching request, correlation, and policy. Historical invocations without it are `LEGACY_MISSING_INVOCATION_CONTEXT`; see `docs/LLM_INVOCATION_CONTEXT_PERSISTENCE.md`.
