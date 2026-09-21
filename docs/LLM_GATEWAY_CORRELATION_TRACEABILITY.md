# LLM Gateway Correlation Traceability

## Trust boundary

The canonical source of LLM operational correlation is the immutable authenticated
`TenantContext` bound by the platform security boundary. `CanonicalLLMGateway` obtains
that context through `current_tenant_context()` and creates an immutable
`LLMInvocationContext`. Provider adapters cannot create, replace or derive trusted
correlation metadata.

`request_id` identifies one LLM request. `correlation_id` is an independent opaque
cross-service operational trace identifier. The Gateway never derives one from the
other. Missing, malformed or sensitive-looking correlations fail closed before a
provider call.

## Persistence and queries

Every newly governed invocation and its request-scoped `PromptAudit` persist the same
correlation ID. Existing request-history queries remain unchanged; the same repository
families also expose `history_by_correlation`. PostgreSQL indexes correlation for
operational lookup while append-only triggers continue to reject `UPDATE` and `DELETE`.

Invocation and audit tables remain tenant-scoped. Runtime queries execute under
PostgreSQL RLS, so identical correlation IDs in different tenants never expose each
other. Missing `TenantContext` returns no rows and blocks writes. Correlation never
replaces tenant authorization.

## Privacy

Correlation is operational metadata and may not encode patient identity, CPF, email,
clinical content, credentials, tokens or secrets. Invocation and audit persistence
continues to store hashes and operational metrics rather than raw prompts, DTOs or
provider output.

## Legacy policy and restart

Migration `030_llm_correlation` adds nullable columns without rewriting historical
append-only records. A historical row with `NULL` correlation is classified as
**LEGACY_UNCORRELATED** by policy: it remains request-queryable and immutable, but is
excluded from correlated Stage-13 evidence. All new governed request-scoped records
require correlation at the repository boundary.

After restart, canonical PostgreSQL repositories reconstruct request and correlation
history directly. No process-local object or inferred identifier is needed.

Restart equivalence for classification and deterministic generation configuration is
defined separately in `docs/LLM_INVOCATION_PERSISTENCE.md`; neither value is inferred
from audit or status.

The complete trusted correlation context is persisted independently and linked by request ID. Restart never re-derives principal, purpose, policy, or issuance time from current security state; see `docs/LLM_INVOCATION_CONTEXT_PERSISTENCE.md`.
