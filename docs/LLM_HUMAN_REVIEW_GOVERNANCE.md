# LLM Human Review Governance

AuditDefense-backed drafts resolve upstream constraints through the owner-side `AuditDefenseReviewGovernanceAdapter`. Dispatch remains behind `UpstreamReviewGovernancePort`; Human Review imports neither Audit Defense repositories nor SQL. Critical limitations and canonical reviewer attribution are preserved without reinterpretation.

Stage 14 reviews exactly one resource: an immutable, persisted `GovernedLLMDraft`. Raw provider responses, gateway DTOs, Patient Context and EvidencePackage are never review inputs.

## Canonical boundary

The flow is `ACTIVE draft reread → integrity and Stage-13 linkage → OIDC human principal → active session/JTI → ExternalIdentityLink → TenantContext → canonical ReviewerIdentity → ReviewerAuthorizationPort → append-only review event`.

Eligibility is fail-closed. The exact draft/version must exist; its content hash, integrity hash and issuance attestation must validate; invocation, invocation-context, prompt and persisted upstream links must agree; its classification and review status must be eligible; and the explicit lifecycle query must return `ACTIVE`. `SUPERSEDED`, `INVALIDATED`, blocked, forged or stale inputs cannot be reviewed. The repository takes the lifecycle advisory lock and rechecks `ACTIVE` in the same transaction as the event insert, closing stale-approval races.

## Decisions and authority

The transitions are `PENDING_REVIEW` to `APPROVED_BY_REVIEWER`, `REJECTED_BY_REVIEWER`, or `NEEDS_CLARIFICATION`. Canonical reviewer roles and authorization policy are reused. Self-approval is prohibited by the existing policy. Unresolved critical upstream validation issues require `SENIOR_REVIEWER` or `ADMINISTRATOR`.

Approval means controlled downstream human use only. `externally_actionable` is always false; Stage 14 grants no diagnosis, treatment, prescription, payer decision, direct-care, public-release or production-healthcare authority.

## Persistence, integrity and privacy

`llm_human_review_events` is tenant-scoped, RLS-enforced, append-only and hash-linked. Runtime writers have SELECT/INSERT only; readers have SELECT only; PostgreSQL rejects UPDATE and DELETE. Events store governance metadata and references, never draft content, JWTs, direct identity, secrets, prompts or provider payloads. The same tenant can reconstruct state after restart; wrong or absent tenant context sees no history.

Draft and persisted-input attestors are composed through the Secrets/KMS boundary. Deterministic keys are permitted only through the test-safe secret adapter; application services receive attestors, never raw key bytes.

## Residual limitations

External actionability remains prohibited. Production IdP/KMS/HSM, institutional IAM policy, formal privacy/legal validation and controlled-pilot operating procedures remain deployment gates.

## Continuous Stage-14 composition

The PostgreSQL acceptance proof composes deterministic signed OIDC, persisted ExternalIdentityLink, canonical Session/JTI replay protection, trusted tenant resolution and authorization, persisted ReviewerIdentity, managed versioned `SIGNING_KEY` attestation, draft/lifecycle reread, review decision and both restart-safe histories without directly constructing the principal or reviewer.

Security auditing is described in `LLM_HUMAN_REVIEW_SECURITY_AUDIT.md`. Pre-tenant authentication/session rejection stays in canonical IAM/session audit; tenant-scoped review audit begins only after trusted tenant resolution.
