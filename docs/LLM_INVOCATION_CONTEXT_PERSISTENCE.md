# LLM Invocation Context Persistence

## Trusted source and scope

`LLMInvocationContext` is immutable operational metadata derived only by `CanonicalLLMGateway` from the authenticated, transaction-bound `TenantContext`. Provider adapters cannot create or mutate it. Persistence contains only `request_id`, `correlation_id`, `tenant_id`, opaque `principal_id`, purpose, policy version, exact `issued_at`, and an integrity hash. It contains no patient identity, clinical content, DTO, prompt, response, JWT, credential, or secret.

## Linkage and transaction boundary

The context is persisted after request, prompt, DTO, provider, and policy validation and before provider invocation. A context-persistence failure prevents the provider call, `LLMInvocation`, and request-scoped `PromptAudit`. Invocation persistence requires matching request, correlation, and policy linkage; audit persistence additionally requires identical temperature and seed.

The existing repositories each own a short transaction. Context, invocation, and audit are therefore not one three-table transaction. An attempted request may retain an immutable context if a later provider or persistence failure occurs; only a complete linked context/invocation/audit chain qualifies as Stage-13 restart evidence.

## PostgreSQL, RLS, and immutability

Migration `032_llm_invocation_context` creates tenant-scoped `llm_invocation_contexts`. PostgreSQL RLS uses the canonical transaction-local tenant setting. Runtime roles remain `NOBYPASSRLS`; the writer has only `SELECT`/`INSERT`, while a trigger rejects `UPDATE` and `DELETE`. Request identity is unique, correlation is indexed, and integrity is recomputed on reread.

The adapter validates tenant, principal, purpose, policy, and correlation against the currently bound trusted context before insertion. Same-tenant reads succeed; wrong-tenant and missing-context reads disclose no row.

## Restart and legacy policy

A new process reconstructs exact values directly from PostgreSQL and never substitutes current security state. The deterministic query path is `request_id → context → invocation → prompt audit`; correlation history remains tenant-bound.

Historical invocations without a context row remain immutable and queryable under existing policy. Their status is `LEGACY_MISSING_INVOCATION_CONTEXT`; nothing is synthesized, and they are ineligible for restart-equivalent Stage-13 evidence.

## Stage-13 rationale

Stage 13 requires disposal and recomposition of gateway, provider, repositories, sessions, and dependency containers. This persistence closes the operational metadata gap without changing provider, prompt, classification, clinical, or scientific semantics.
