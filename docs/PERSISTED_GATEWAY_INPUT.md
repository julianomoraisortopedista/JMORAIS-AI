# Persisted Gateway Input

For `AuditDefense`, the canonical owner input is obtained after restart through `AuditDefenseQueryPort.get_exact(PersistedDefensePackageReference)`. The resulting exact package is passed to `issue_from_package()`; scalar package identity, `latest()` and manifest-derived trust are prohibited.

## Trust problem and boundary

An allowlisted DTO alone cannot prove which durable artifact version it represents. The review-eligible Gateway path therefore accepts `PersistedGatewayInput`: an immutable atomic binding of the canonical DTO, `UpstreamArtifactReference`, DTO hash, resolution time and issuer attestation. The reference contains artifact type, canonical stream or artifact ID, exact positive version, tenant, owner integrity reference, policy and owning bounded context; it never duplicates the persisted payload.

Constructing the dataclass does not grant trust. A shared HMAC attestor verifies the complete DTO/reference binding. Its key must be obtained through the canonical secrets boundary in homologation/production composition and is never stored in the artifact or Gateway tables.

## Trusted issuance and owner responsibilities

Issuance belongs to the artifact owner:

```text
tenant-bound owner repository
→ exact persisted version reread
→ owner validation
→ canonical DTO projection
→ deterministic owner integrity reference
→ attested PersistedGatewayInput
```

Current issuers cover `MedicalDocumentVersion → MedicalDocument`, `DefensePackage → AuditDefense`, `OrthopedicAssessmentSet → OrthopedicAssessment`, and persisted `ClinicalReasoningInput`. They query an exact version, never silently substitute `latest()`. `CanonicalStructuredDTO` remains eligible for legacy non-review Gateway use but is `NOT_ELIGIBLE_FOR_PERSISTED_REVIEW_FLOW` because it has no canonical durable owner identity.

For controlled Stage 13, Audit Defense uses `issue_from_package(DefensePackage)`.
The typed package must already be an exact canonical reread, but the issuer still
rereads its stream/version, requires full equality, validates the predecessor chain
and resolves the Stage-11 document reference before issuing. The legacy scalar
`issue(stream_id, version)` remains compatibility-only and is not eligible for the
governed COMPLETE_CASE path.

## Canonical persistence and Gateway enforcement

`PersistedGatewayInputRecord` is the durable, metadata-only representation of the trust artifact. Its canonical repository/query ports support append, identity lookup, exact upstream lookup, and request/invocation linkage. PostgreSQL migration `043_persisted_gateway_inputs` stores the opaque identity, exact upstream reference, DTO hash, original HMAC signature, managed-key reference, issuance time, policy and record integrity hash. It never stores the DTO, prompt, model output, clinical free text or identity.

Persistence verifies the owner-issued binding before append. The original signature is retained unchanged; restart verification resolves its opaque key ID/version through the canonical Secrets/KMS ports. Revoked or unavailable keys fail closed, and no raw key material is stored in PostgreSQL.

`invoke_persisted()` verifies attestation, DTO hash, exact artifact-type/DTO mapping and tenant equality before provider invocation. It then applies the existing allowlist, prompt, policy, privacy and provider gates. The Gateway imports no owner repository and does not independently validate clinical semantics. Providers receive only the existing encoded DTO and do not participate in upstream trust.

The resulting `LLMInvocation` stores the typed upstream reference and `persisted_gateway_input_id`. PostgreSQL enforces that this foreign key resolves to the same tenant and exact artifact type/ID/version before appending the invocation. No clinical DTO, prompt or provider response is added to operational persistence. Historical invocations without this identifier remain immutable `LEGACY_MISSING_PERSISTED_GATEWAY_INPUT` records and cannot prove a complete review flow.

## Tenant, restart and future handoff

Owner reread occurs under existing PostgreSQL RLS and the reference tenant must equal the transaction-bound `TenantContext`. Cross-tenant bindings fail before provider invocation. The table uses forced RLS for runtime roles and rejects UPDATE/DELETE. After restart, `PersistedGatewayInputTrustService` rereads the record, resolves the exact owner version (never `latest()`), recreates the canonical DTO projection, recomputes its hash and verifies the original attestation through the managed-secret boundary.

The persisted record is included in global cryptographic replay. Replay validates canonical payload/relational equality, record hash and invocation references; failure makes the stream `TAMPERED`. This provides the restart-safe backward-trace segment `LLMInvocation → PersistedGatewayInput → exact upstream artifact`. It does not duplicate reviewable content, which remains owned by `GovernedLLMDraft`.
