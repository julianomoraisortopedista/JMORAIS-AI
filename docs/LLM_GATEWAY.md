# Canonical LLM Gateway — MIP-10

## Exclusive boundary

`jmoraIs.llm_gateway` is the only bounded context permitted to communicate with model providers. It accepts exact canonical DTO types: validated `MedicalDocument`, `AuditDefense`, `OrthopedicAssessment`, `ClinicalReasoningInput`, or an explicitly versioned `CanonicalStructuredDTO`. ORM objects, raw database entities, Patient Context, EvidencePackage, connector output, arbitrary text, direct identity and secret-like fields fail closed.

## Prompt and output governance

Prompts are immutable, versioned, SHA-256 protected and append-only. A prompt declares allowed DTO types, purpose, output schema and policy version. Invocation requires an explicit human-review policy that prohibits external actionability. Provider success is at most `APPROVED_FOR_REVIEW`; refusal is `BLOCKED`. No output is a diagnosis, treatment, recommendation or autonomous decision.

## Providers, privacy and observability

OpenAI, Azure OpenAI, Anthropic, Google Gemini and local adapters depend only on an injected transport; tests perform no external calls. The OpenAI adapter is prepared for the Responses API behind this transport boundary. Provider credentials never enter domain DTOs or audit records. Audits persist hashes and operational metadata—not prompt payloads, canonical DTOs or model output—including provider, model, temperature, seed, tokens, cost, latency, retries, rate limits, timeouts and policy.

## Persistence and limitations

Prompt versions, audits and invocations are append-only in memory and PostgreSQL. PostgreSQL uses immutable JSONB history and rejects UPDATE/DELETE. Production remains blocked on secrets management, provider-specific authenticated transports, contractual privacy assessment, regional routing, zero-retention controls, model allowlists, live rate-limit policy, cost budgets, output safety evaluation and institutional approval.

Invocation and request-scoped audit history preserve the opaque correlation ID obtained
only from the authenticated `TenantContext`. Request and correlation identities remain
distinct and tenant-bound correlation queries rely on PostgreSQL RLS. Historical rows
without correlation remain immutable `LEGACY_UNCORRELATED`; see
`docs/LLM_GATEWAY_CORRELATION_TRACEABILITY.md`.

Completed invocation history also preserves the exact canonical output classification
and the request's temperature/seed. Classification is never inferred from provider
status, and PromptAudit configuration must match invocation configuration. Historical
incomplete rows remain explicit legacy state; see `docs/LLM_INVOCATION_PERSISTENCE.md`.

The trusted `LLMInvocationContext` is persisted through a mandatory canonical repository before provider invocation. Tenant, opaque principal, purpose, policy, correlation, request identity, and exact issuance time are restart-safe without storing clinical or generated payloads. See `docs/LLM_INVOCATION_CONTEXT_PERSISTENCE.md`.

Review-eligible invocations additionally require an owner-issued `PersistedGatewayInput`. Before provider invocation, the Gateway verifies and canonically persists its metadata-only trust record. `LLMInvocation.persisted_gateway_input_id` links to that record while the existing upstream scalars remain independently consistency-checked. The Gateway never queries owner repositories or stores the DTO. Legacy rows without the durable link are explicitly ineligible for final backward-trace evidence. See `docs/PERSISTED_GATEWAY_INPUT.md`.

For persisted-input invocations the Gateway also records an independent SHA-256 hash of the exact safe output bytes. It does not persist that output. The separate Governed LLM Draft bounded context validates the hash and owns any durable reviewable content; see `docs/GOVERNED_LLM_DRAFT.md`.

Completed canonical invocations may receive a Gateway-owned
`PersistedLLMInvocationReference`. Its exact query revalidates the invocation,
context, PromptVersion, persisted Gateway input, upstream artifact, tenant, policy,
provider/model, classification/status and generation configuration after restart.
The reference is metadata-only and is the mandatory typed linkage for new governed
draft exact references; see `docs/LLM_INVOCATION_EXACT_REFERENCE.md`.
