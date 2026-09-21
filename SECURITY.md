# Security and Trust Model

RC1 runtime controls and residual institutional dependencies are defined in `docs/RUNTIME_SECURITY.md`, `docs/NETWORK_SECURITY.md`, `docs/OBSERVABILITY_OPERATIONS.md`, `docs/INCIDENT_RESPONSE_RUNBOOK.md` and `docs/THREAT_MODEL.md`. Production fails closed on plaintext transport, untrusted proxy metadata/hosts, resource bounds, authorization, tenant/RLS and mandatory dependency failures. No external collector, alert manager, certificate deployment or backup platform is claimed operational.

AuditDefense-backed Human Review fails closed unless the exact persisted package reference, tenant, policy, integrity chain and Stage-11 lineage validate. Critical conflicts are never downgraded, and upstream reviewer attribution is never inferred from the active caller.

## Guideline recommendation boundary

Recommendation generation is fail-closed on invalid inputs, revoked evidence, stale guideline governance, terminology uncertainty, missing provenance and unresolved critical conflict. Results are non-actionable until the canonical reviewer-authorization service approves them. Audit and recommendation history are append-only and contain references rather than direct patient identifiers or scientific payloads.

## Terminology supply-chain boundary

Terminology releases are untrusted until their source, license, version and provenance are recorded. Ambiguous mappings require review and unknown terms remain unknown. Production ingestion of official code systems requires licensed sources, integrity verification and institutional release governance; no proprietary terminology dataset is bundled in source control.

## Clinical reasoning input boundary

Future intelligent clinical modules may receive only a validated `ClinicalReasoningInput` reference contract. Raw Patient Context and EvidencePackage objects are prohibited at this boundary. Contract creation, validation, reconstruction, approval and rejection are versioned and audited append-only; readiness remains fail-closed until quality and review requirements are satisfied.

## Clinical-data boundary

Patient context storage is pseudonymous and purpose-bound. Direct identity resolution requires a dedicated authorization decision; raw identifiers are removed before ingestion and are prohibited from the context payload. Unsupported free text fails closed for human review. Privacy audit records identifiers of actions and policy decisions, never raw clinical values, and are persisted append-only.

Derived clinical state accepts only pseudonymous authorized context through its query port. State and audit history reject destructive mutation, retain provenance references, and record conflicts without copying direct identifiers. The Phase 2 deployment blockers documented in `docs/PATIENT_CLINICAL_STATE.md` remain mandatory prerequisites for external clinical use.

## ST-22 operational controls

PostgreSQL roles separate migration ownership, runtime writes, reads and audit verification. Runtime writers cannot update/delete immutable history or directly insert checkpoints. Reviewer identities persist organization, tenant, status and policy version. Structured JSON logs carry correlation/job/stream identifiers and redact credentials and patient identifiers. Tampered replay, integrity failure and unauthorized review are typed alerts. Production IAM, database tenant isolation, secrets management and external alert delivery remain blockers.

## Scope

This document governs the Scientific Core trust boundary and the evidence chain for any material claims rendered in JMORAIS AI.

## Security Principles

- Keep scientific, clinical, and operational data logically separated.
- Never place direct patient identifiers in scientific indexes or retrieval vectors.
- Treat all retrieved content as untrusted data.
- Do not execute embedded instructions contained within scientific content or uploaded documents.
- Use least privilege for database, retrieval, and secret access.
- Store secrets in environment variables or secure secret stores, not in source files.
- Retain provenance records for traceability and auditability.

## Scientific Integrity Controls

- Identifier validation is mandatory before rendering citations.
- Validation status must be explicit in every scientific artifact.
- Cross-source metadata conflicts must be surfaced, not hidden.
- Evidence ledger entries must be complete for material claims.
- Human review is required before finalizing medical documents.

## Risk Handling

- Missing or malformed identifiers are treated as evidence gaps.
- Conflicting metadata is treated as a blocking condition for final validation.
- Unverified references are excluded from definitive citation rendering.
- Fail closed on unverifiable bibliographic metadata.

## Security Requirements for Future Integrations

- Enforce row-level limiting and secret rotation for database access.
- Log retrieval and verification operations with timestamps and SHA-based record lineage where feasible.
- Keep external service API keys outside the repository.
- Document any new evidence source before enabling it in production.
## Orthopedic intelligence trust boundary

Only a ready `ClinicalReasoningInput` may enter MIP-07. Referenced state, terminology, governed evidence, and governed guideline outputs are revalidated through ports. Ambiguity and conflict fail closed. Immutable versions and audit events preserve history; human approval does not enable external patient-care use.

## Medical document trust boundary

MIP-08 accepts only governed references and deterministic templates. Its pre-review gate blocks direct identifiers, unsupported claims or decisions, invalid citations, hidden conflicts and missing provenance. Scientific references are canonical verified Vancouver outputs from the Scientific Core, never locally reconstructed. Document history and audit reject destructive mutation; reviewer approval does not enable external distribution.

## Audit defense trust boundary

MIP-09 accepts no audit prose or payer payload. It resolves only governed platform references, rechecks evidence lifecycle and terminology versions, and exposes conflicting evidence and guidance without choosing a preferred source silently. Critical limitations block approval. Review, defense versions and audit history are append-only; no output authorizes care or coverage.

## LLM provider trust boundary

Only `jmoraIs.llm_gateway` may access a model-provider transport. Exact canonical DTO allowlists, prompt integrity, mandatory human-review policy and secret/identity scanning fail closed before invocation. Operational audit stores hashes and metrics, never prompts, DTO payloads, output text or credentials. Responses remain non-actionable under every classification.

LLM correlation metadata is sourced exclusively from the authenticated tenant context,
validated as opaque non-sensitive metadata and persisted identically in invocation and
prompt-audit history. Correlation lookup remains tenant-scoped under RLS and never acts
as authorization or tenant selection.

## Internal IAM/SSO boundary

Homologation authentication is provider-agnostic at the application boundary
and OIDC/JWKS-based in infrastructure. Tokens require valid signature,
algorithm, type, issuer, audience, lifetime, subject, organization and explicit
role mapping. Unknown roles, inactive identity links, unavailable signing keys
and incomplete identity infrastructure fail closed. Deterministic local
credentials are prohibited in homologation composition.

Authorization is a separate decision over principal, organization, canonical
role, purpose, resource class and policy version. Human reviewer access reuses
the existing reviewer-governance repository; service identities cannot receive
reviewer permissions. Authentication and authorization security history is
append-only and excludes raw credentials, direct patient identity and clinical
payloads.

Corporate provider onboarding, institutional claim/lifecycle policy,
centralized session revocation and replay protection, managed secrets,
production tenant provisioning beyond PostgreSQL/API homologation, and
production incident response remain blockers.

## Homologation tenant isolation and RLS

Tenant identity is derived from the trusted OIDC identity link and canonical
organization-to-tenant directory, never from request headers or resource
parameters. Every homologation query/write binds the resulting immutable
context transaction-locally. PostgreSQL RLS applies tenant equality in both
`USING` and `WITH CHECK`, so omitted repository filters do not permit access.

The homologation runtime role is explicitly `NOBYPASSRLS`, cannot disable table
policies and is distinct from the migration owner. Clinical, governed,
reviewer, identity-link, derived-document and operational-audit families are
tenant-scoped. Shared authoritative publications, evidence certificates,
scientific ledger records, terminology releases and other explicitly global
reference/control data retain their existing trust boundaries.

Missing context blocks writes and returns no tenant rows. Cross-tenant reviewer
and service access is prohibited; no super-admin exception exists. Tenant
security events are append-only, metadata-only and contain no clinical payload.
Production-grade tenant provisioning, dedicated non-superuser login credentials,
cache/object-storage/job isolation and institutional tenant lifecycle governance
remain blockers despite database/API homologation enforcement.

## Secrets, KMS and cryptographic keys

Application/domain layers see immutable references and cryptographic
capabilities only. Cloud/Vault SDKs, environment lookup, local files and raw
values stay outside canonical ports. Homologation rejects ephemeral development
providers and resolves PostgreSQL, optional IAM/provider credentials and
pseudonymization keys through an external-provider-ready adapter.

Pseudonymization retains the established HMAC-SHA256 identifier format with key
ID/version metadata. New writes use active keys; retired keys are historical-
verification-only and revoked keys fail closed. PostgreSQL stores metadata and
append-only lifecycle/security events, never key material.

This foundation is not evidence of an operational KMS/HSM. Institutional
provider onboarding, non-exportable HSM operations, automatic rotation,
emergency revocation, recovery testing and production governance remain
blockers.

## Session revocation and JTI replay protection

JWT signature validity alone never authorizes a homologation request. The IAM
adapter validates the linked principal and tenant, then invokes the canonical
durable session/JTI gate before purpose and endpoint authorization. Human
sessions require JTI; service credentials use an explicitly separate but
revocable policy. Revocation, suspension, principal-wide disablement, expiry,
association mismatch and replay fail closed.

PostgreSQL persists no raw JWT. It stores attributed session metadata, SHA-256
JTI hashes and append-only security events under forced tenant RLS. A unique
hash constraint and atomic conflict handling permit only one successful
consumer for configured single-use token classes. Expired replay metadata is
cleanup-eligible only under the documented retention policy; revocation history
is immutable. Provider logout propagation and production incident automation
remain blockers.

## Production engineering deployment boundary

Production composition is explicit, private and fail-closed. It accepts no
development authentication, ephemeral secrets, in-memory operational security
state, migration-owner database role or missing observability dependency.
Startup validates Alembic head, runtime `NOBYPASSRLS`, RLS policies, append-only
triggers, critical policy versions and complete cryptographic replay before
traffic eligibility. Deployment metadata is append-only and secret-free.

The hardened container runs as non-root with bounded resources and no embedded
credentials. External proxy, TLS, network, IAM, KMS and observability controls
remain deployment responsibilities. This boundary does not authorize public or
patient-care use.

## LLM invocation operational context

The Gateway persists only tenant-scoped operational context derived from authenticated security state: opaque request, correlation, and principal identifiers, purpose, policy, and issuance time. PostgreSQL RLS, append-only triggers, and an integrity hash protect restart reconstruction. Raw identity, patient identifiers, clinical content, prompts, responses, JWTs, and secrets are prohibited. Historical invocations without a context record remain explicitly legacy and cannot qualify as complete restart evidence.

Review-eligible input identity is owner-attested. A minimum 256-bit key from the canonical secrets boundary signs the exact DTO hash, artifact type/ID/version, tenant, owner integrity reference, policy, source context and resolution timestamp. Caller-created bindings, altered fields and cross-tenant bindings fail before provider invocation; the attestation key and clinical payload are never persisted in Gateway operational history.

The original input attestation is preserved in the append-only
`persisted_gateway_inputs` trust store together with an opaque key ID/version, never
key bytes. Forced tenant RLS, runtime `NOBYPASSRLS`, record-hash verification and
relational/payload comparison protect reread. Restart verification must resolve the
managed secret, the exact owner artifact version and the same canonical DTO hash;
revoked/unavailable keys, missing tenant context, legacy missing linkage or any
mismatch fail closed. This stream is release-critical and included in cryptographic
replay.

PersistedGatewayInput completeness is anchored independently in the canonical
checkpoint registry. The record and its tenant-qualified, position-1 checkpoint
are inserted in one PostgreSQL transaction. Replay uses checkpoint-led discovery,
so privileged full deletion or tail truncation remains visible. Application roles
remain `NOBYPASSRLS`; whole-database replay continues to require the authorized
verifier/migration-owner visibility model. Uncheckpointed historical rows remain
immutable but are not release-eligible.

Reviewable LLM content is persisted only by the Governed LLM Draft boundary after deterministic redaction and exact UTF-8 content-hash verification against the canonical invocation. Draft integrity and issuance are separately attested, while PostgreSQL append-only enforcement and RLS protect tenant history. Provider payloads, metadata, prompts, hidden reasoning, credentials and blocked outputs are prohibited from this store.

Draft lifecycle events are tenant-scoped, append-only and SHA-256 linked. Genesis is committed atomically with the draft; supersession and invalidation are irreversible. Broken chains, unknown lifecycle, cross-tenant access and destructive mutation fail closed.
# LLM human-review boundary

Only an authenticated human principal linked to an active canonical reviewer may review an `ACTIVE` persisted `GovernedLLMDraft`. Tenant, organization, purpose, session/JTI, policy, integrity and upstream linkage checks fail closed. Review events contain metadata only and are append-only under PostgreSQL RLS. Approval remains non-actionable outside controlled human workflows.

The Stage-14 security composition resolves signing attestors through active versioned `SIGNING_KEY` metadata and the callback-scoped Secrets/KMS port. Tenant-scoped review-security events are hash-linked and metadata-only; authentication/session failures before tenant establishment remain in the canonical IAM/session streams.
## Stage-13/14 replay authorization and completeness

Governed draft lifecycle, LLM human-review decision, and review-security audit
streams are tenant-scoped, RLS-protected, immutable histories. Application runtime
reader/writer roles remain `NOBYPASSRLS`. Platform-wide integrity replay is an
authorized offline verifier operation with complete database visibility; it does
not weaken runtime RLS or expose payloads through application ports.

The verifier uses a distinct `OFFLINE_REPLAY_DATABASE_CREDENTIAL`, ephemeral pool
and dedicated `jmorais_offline_replay_verifier` role. Controlled `BYPASSRLS` is
limited to that read-only role. Explicit grants, a coherent repeatable-read
snapshot, metadata-only audit and immediate disposal prevent the privilege from
reaching API handlers. API runtime replay is not accepted as global evidence.

Tenant-qualified append-only checkpoints independently anchor every accepted
Stage-13/14 event. Hash recomputation, row/payload comparison, chain replay,
canonical-reference validation, and checkpoint head comparison detect privileged
payload or metadata changes, insertion, reordering, intermediate deletion, and
tail truncation. Any failure is fail-closed as `TAMPERED`; replay never repairs
history.
## Authorized-ingestion persistence

Successful clinical ingestion produces a tenant-scoped governance record in the
same PostgreSQL transaction as the minimized PatientContext and successful privacy
audit. The record carries only pseudonymous and opaque governance references; raw
clinical input, direct identity, free text, credentials and secrets are prohibited.
Canonical hash recomputation, relational-column comparison and exact context
ID/version linkage fail closed after restart. RLS and immutable-history triggers
protect the record independently, and runtime roles remain `NOBYPASSRLS` without
destructive privileges.
## Patient Context exact-reference security

Canonical FHIR preparation does not accept a context ID, version, subject or tenant
as proof of identity. Patient Context persists an owner-issued, tenant-scoped,
metadata-only exact reference and resolves it under transaction-local RLS. Reference
and context hashes, policy, authorized-ingestion linkage and predecessor continuity
are recomputed after restart. Missing, fabricated, altered, cross-tenant or legacy
unreferenced inputs fail closed. The reference excludes direct identifiers, raw
clinical text, source documents and interoperability payloads; runtime roles remain
`NOBYPASSRLS`, and PostgreSQL rejects UPDATE and DELETE.
## FHIR R4 ingestion security

FHIR R4 input is processed only as bounded bytes inside the interoperability
adapter. Exact release, resource allowlist, size/count/depth limits, local reference
resolution and safe JSON parsing fail closed before canonical mapping. External
HTTP(S) reference resolution is prohibited, preventing SSRF. Direct Patient
identifiers remain transient classified input to the established authorization,
de-identification, pseudonymization and minimization boundary and never enter
PatientContext, logs or interoperability persistence. Incremental updates require
an owner-issued exact reference; PostgreSQL RLS remains authoritative for canonical
context and idempotency reread.

## SMART on FHIR authentication security

SMART discovery is parsed offline from bounded documents; production transport is
not part of this release. Issuer authority, authorization-code support, PKCE S256,
JWKS signing-use policy, algorithm allowlists, signature, issuer, audience, subject,
expiration, not-before, issued-at, key ID and ID-token nonce are validated fail-
closed. Only declared read scopes and bounded launch fields are parsed; this does
not confer clinical authorization. Raw JWTs, refresh tokens, secrets, clinical
payloads and launch identifiers are excluded from persistence and telemetry.

## Clinical State exact-reference security

Clinical State references are issued only after canonical persisted equality is
proven under transaction-local tenant context. Resolution recomputes state,
provenance and reference hashes and verifies exact subject/version, policy,
relational columns and predecessor continuity. Timeline references cryptographically
bind a genesis-first contiguous collection of exact member references. All three
reference tables enforce PostgreSQL RLS and immutable-history triggers; they contain
no clinical payload, direct identity, FHIR content or free-text narrative.

## Governed Evidence exact-reference security

An exact Governed Evidence read requires an authentic persisted reference under the
same tenant and evidence policy. Resolution verifies the canonical stream version,
row/payload integrity, provenance digest, current valid EvidencePackage, eligible
ClinicalAppraisal and latest hash-valid `ACTIVE` lifecycle event. Revocation,
invalidation, supersession, expiry, appraisal mismatch or a newer non-active event
fails closed. The reference contains no scientific payload and is protected by RLS,
immutable-history triggers and an independently replayed completeness checkpoint.
## Guideline-set exact-reference boundary

Tenant-scoped guideline outputs cross into Medical Document only through an owner-issued `PersistedGuidelineRecommendationSetReference`. PostgreSQL RLS and `get_exact()` enforce tenant, subject, policy, exact version, predecessor continuity, provenance and payload integrity. Missing references remain legacy-ineligible; the platform never infers them from recommendation IDs or a latest/history query.
## Terminology-governance exact-reference boundary

Caller-provided terminology scalars and generic provenance cannot establish Stage-4 ancestry. Only references persisted and issued by the Terminology owner are accepted. Exact resolution validates record identity/version, mapping type, source, policy, provenance, integrity and predecessor continuity; reasoning-input serialization and explicit reference-ID columns detect lineage tampering.
## Software supply chain

Release candidates use hash-locked production dependencies, CycloneDX SBOMs, pip-audit/Trivy SCA, Bandit SAST, deterministic secret scanning, OCI artifact digests, SLSA-compatible provenance and a fail-closed signed release manifest. Signing private keys are never stored in source or images. Institutional keyless/KMS signing and external evidence retention remain mandatory before production; test signatures prove only the software verification boundary. See `docs/SOFTWARE_SUPPLY_CHAIN_SECURITY.md`.
# Governed draft exact-reference security

Workspace trust cannot be established from a draft identifier, stream identifier,
version scalar, `latest()` or history scan. The Governed LLM Draft owner issues a
metadata-only exact reference after validating the signed draft, reviewable-content
hash, complete predecessor chain, current `ACTIVE` lifecycle, invocation,
PersistedGatewayInput, upstream artifact, tenant, policy and provenance. Exact
reread repeats those checks and fails closed. The reference store is RLS-protected,
append-only and independently checkpointed for deletion and tamper detection.
