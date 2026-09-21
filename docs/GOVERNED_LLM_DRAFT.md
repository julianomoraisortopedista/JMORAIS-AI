# Governed LLM Draft

## Boundary

`jmoraIs.governed_llm_draft` owns the only durable artifact eligible for future human review after Stage 13. It is separate from the operational LLM Gateway and does not contact providers, perform clinical reasoning, authorize reviewers or create approval events.

```text
PersistedGatewayInput
→ CanonicalLLMGateway
→ classified LLMResponse
→ persisted LLMInvocation with independent content hash
→ GovernedLLMDraft issuance
→ append-only PostgreSQL/RLS
→ restart-safe query
```

## Issuance and content integrity

Issuance requires an attested persisted input, the exact persisted successful invocation, its trusted invocation context, an eligible classified response and mandatory non-actionable review policy. Request, correlation, tenant, prompt, provider, model, upstream reference, classification and independent `reviewable_content_hash` must agree.

The content hash is SHA-256 over the exact UTF-8 bytes presented for review. It is independent from the provider-oriented `response_hash`. Only redacted reviewable text is persisted. Outputs needing further redaction cannot silently diverge from the Gateway hash and fail closed. Blocked, failed, timed-out, rate-limited, provider-bypassed or unlinked outputs cannot issue drafts.

The draft is immutable and carries an integrity hash plus HMAC issuance attestation. Direct dataclass construction does not make an artifact persistable. The attestation key is injected through the secrets boundary and is never persisted.

## Versioning, persistence and scope

Draft streams are derived from the upstream artifact identity. Genesis is version 1 with no predecessor; later drafts append the exact prior draft ID. PostgreSQL uses advisory stream locks, a unique tenant/stream/version constraint, an append-only trigger and tenant RLS. Runtime readers and writers cannot update, delete or bypass RLS.

Operational Gateway tables retain hashes and references only. Reviewable content exists solely in `governed_llm_drafts`. Human Review remains deliberately out of scope.

Every canonical draft is persisted atomically with an append-only `ACTIVE` lifecycle genesis. Later supersession or invalidation is represented by hash-linked events without mutating draft history. See `docs/GOVERNED_LLM_DRAFT_LIFECYCLE.md`.
# Stage 14 consumption

The only canonical consumer for human LLM review is `AuthorizedLLMHumanReviewService`. It accepts an exact persisted draft reference, never a raw Gateway response. See `LLM_HUMAN_REVIEW_GOVERNANCE.md`.
# Exact persisted reference

S003 consumers must use
`PersistedGovernedLLMDraftReference → get_exact(reference)`. Scalar `draft_id`,
`latest()` and stream-history reads are compatibility paths and cannot establish
Workspace trust. The exact contract is documented in
`docs/GOVERNED_LLM_DRAFT_EXACT_REFERENCE.md`.
