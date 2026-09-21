# JMORAIS-AI Internal API v1

The first API surface is a read-only application adapter at
`/internal/api/v1`. It is exclusively for internal engineering, scientific
validation, clinical-governance evaluation and controlled pilot development.
It is not a public API and is prohibited for production healthcare, direct
patient care, autonomous decisions, payer authorization or regulatory claims.

The adapter consumes existing canonical query ports. It never serializes ORM
models, PatientContext or EvidencePackage. ClinicalReasoningInput must be
approved and ready; GovernedEvidence must pass its integrity-aware query port
and have an ACTIVE lifecycle; downstream artifacts must have completed the
canonical reviewer workflow. Every response is an explicit versioned DTO.

The homologation IAM and tenant-isolation foundations do not authorize external
exposure. Bind the service only to loopback or an isolated homologation network.
Correlation IDs are returned as `x-correlation-id`; error responses use stable
`code`, `message` and `correlation_id` fields.

## Internal authentication and authorization

Except for liveness, every endpoint requires `Authorization: Bearer <token>`
and an explicit `x-purpose`. Role and policy version are resolved by
`ApiAuthenticationPort`; caller-supplied roles are never trusted. The
deterministic adapter supports `INTERNAL_SERVICE`, `CLINICAL_REVIEWER` and
`ADMINISTRATOR` solely for development and tests. It hashes configured tokens,
performs constant-time comparison and can never be composed for homologation.

Purpose values are `INTERNAL_OPERATIONS`, `SCIENTIFIC_VALIDATION`,
`CLINICAL_REVIEW` and `ADMINISTRATION`. Missing credentials, malformed caller
context, unsupported purpose and unauthorized role fail closed. Reviewer-only
clinical artifacts cannot be read by a service identity.

Every request creates an access-audit event and timing metric containing only
caller metadata, route template, status, duration, correlation ID and policy
version. Query values, resource identifiers and clinical payloads are excluded.
Audit persistence failure blocks the response.

## Operational readiness and ASGI

Readiness is authenticated and reports application composition, PostgreSQL
connectivity, Alembic migration status and critical dependency checks. It
returns HTTP 503 whenever any required check fails. Liveness proves only that
the process can answer and intentionally does not imply readiness.

The fail-closed ASGI development entry point starts on loopback only:

```bash
JMORAIS_DEV_INTERNAL_TOKEN='<at-least-24-random-characters>' \
  .venv/bin/uvicorn jmoraIs.api.asgi:app --host 127.0.0.1 --port 8000
```

Its default composition has no clinical repositories and therefore remains
`NOT_READY`. A homologation composition root must explicitly inject all
canonical query adapters and the PostgreSQL readiness adapter. Never bind this
configuration to `0.0.0.0` or publish its OpenAPI endpoint.

Operational endpoints are `/health/live`, `/health/ready` and `/version` under
the versioned prefix. Resource endpoints expose approved reference summaries
for ClinicalReasoningInput, GovernedEvidence, GuidelineRecommendationSet,
OrthopedicAssessmentSet, MedicalDocument and AuditDefense. Collection members
embedded in a resource use bounded `offset`/`limit` pagination.

Request bodies are capped at 1 MiB, OpenAPI exists only under the internal
prefix, errors never include stack traces, and no direct identity or clinical
payload is written to API access audit or metrics.

## Homologation composition and observability

`compose_homologation` is the sole explicit homologation composition root. It
wires the PostgreSQL package catalog, GovernedEvidence and lifecycle services,
ClinicalReasoningInput query service, guideline, orthopedic, document and audit
defense repositories, durable reviewer authorization/governance, operational
audit, metrics, structured logging and readiness adapters. Startup is rejected
unless PostgreSQL, Alembic head, repository composition, audit storage,
authentication, metrics and critical governance checks are all available.

Operational audit is append-only in `api_access_audit_events`; PostgreSQL
triggers reject update and delete. Its schema intentionally has no general
payload, patient ID, PatientContext or EvidencePackage column. Metrics implement
an OpenTelemetry-compatible counter/histogram port without requiring a collector
and cover request count, latency, status codes and authentication,
authorization, readiness and audit failures.

Structured JSON logging contains only correlation ID, caller/service ID, route
template, purpose, status, duration, policy version and timestamp. A redaction
adapter removes credential-like values. Tokens, secrets, direct identity,
resource/query values and clinical content are prohibited.

Health states are distinct: `LIVE` means process response only, `READY` means
all mandatory dependencies passed, `DEGRADED` means a non-blocking check reports
degradation, and `NOT_READY` returns HTTP 503. Configuration objects exist only
for development, test and homologation. No production configuration is defined
or authorized.

## Homologation IAM/SSO boundary

Homologation requires an explicit `OIDCProviderConfig` and uses
`OIDCIdentityProviderAdapter` as its only authentication mechanism. It validates
JWT type, signature, allowed algorithm, key ID, issuer, audience, expiration,
authentication time, subject, organization and required claims. Signing keys
come from configured JWKS with bounded caching and refresh on rotation. Failure
to establish a trusted key makes readiness `NOT_READY`. PyJWT supplies the
cryptographic implementation; no custom cryptography is defined.

External roles are translated by an explicit allowlist into canonical roles;
unknown claims fail closed. The immutable `AuthenticatedPrincipal` is not an
authorization decision. A separate policy checks role, purpose, resource class,
organization and policy version outside route handlers. Service principals have
explicit purposes and scopes and cannot inherit human reviewer privileges.

Persistent `ExternalIdentityLink` records associate an external subject with an
internal pseudonymous principal and, for humans, the existing canonical
`ReviewerIdentity`. Only `ACTIVE` links authenticate; suspended or disabled
links are rejected. Authentication outcomes, authorization denials and link
transitions are written to append-only `identity_security_events`, without raw
tokens, keys, direct patient identity or clinical content.

Provider endpoints and database credentials must be injected by the deployment
configuration/secret abstraction. Homologation startup requires OIDC/JWKS,
identity and reviewer repositories, authorization policy, PostgreSQL and the
current Alembic revision. This remains internal homologation infrastructure and
does not authorize production healthcare use.

## Canonical tenant and PostgreSQL RLS boundary

Every authenticated homologation request resolves an immutable `TenantContext`
from the trusted external identity association. It contains tenant,
organization, principal, role, purpose, policy version and correlation ID.
Clients cannot choose a tenant: `x-tenant-id` and equivalent caller-supplied
tenant selection are rejected. Human reviewers and service identities are
tenant-scoped; no unrestricted super-admin policy exists.

The homologation composition uses a transaction-local PostgreSQL context
(`jmorais.tenant_id`) and executes repository operations with
`jmorais_application_writer`, a `NOBYPASSRLS` role. RLS `USING` and `WITH CHECK`
policies protect Patient Context/Clinical State history, ClinicalReasoningInput,
GovernedEvidence and governance history, guidelines, orthopedic assessments,
medical documents, audit defenses, reviewers, external identity links, API
audit, and tenant-scoped LLM operational records. Queries without an application
tenant predicate remain isolated by PostgreSQL itself. Missing context exposes
no rows and blocks writes.

Canonical scientific publication metadata, the Scientific Ledger,
EvidencePackage catalog, terminology releases, prompt templates and the tenant
directory are explicitly shared reference/control data in this phase. Their
trust boundaries remain unchanged; organization-specific derivatives are
tenant-scoped.

Homologation readiness verifies the tenant repository, required RLS policies,
tenant-aware repository composition and that the active runtime role has no
`BYPASSRLS`. The migration owner is intentionally not accepted as evidence of
runtime isolation. Tenant resolution failures, cross-tenant denials, missing
contexts and unauthorized associations produce append-only metadata-only
security events.

## Session revocation and replay boundary

Cryptographic JWT validation is followed by durable session and JTI validation
before purpose authorization or protected repository access. Human sessions
require a canonical session identifier and JTI. Revoked, suspended, expired or
misattributed sessions fail closed; principal-wide revocation also invalidates
reviewer access. Service principals follow a separate revocable-credential
policy and cannot inherit reviewer semantics.

Only SHA-256 JTI hashes and attributed metadata are persisted. Atomic unique
insertion prevents concurrent consumption of a single-use JTI. Homologation
requires PostgreSQL-backed session, replay and audit repositories with tenant
RLS; see `docs/SESSION_REVOCATION_REPLAY.md`.

## Production engineering composition

The production profile has an explicit composition root and ASGI factory with
no development fallback. Startup requires current migrations, safe runtime
role/RLS, append-only triggers, managed secrets, IAM/JWKS, session security,
durable audit/metrics/logging and valid cryptographic replay. The authenticated
`/internal/api/v1/build` endpoint exposes safe release metadata only. See
`docs/PRODUCTION_COMPOSITION.md` and `docs/DEPLOYMENT_SECURITY.md`.

## Homologation secrets and key boundary

Homologation configuration contains only managed `SecretReference` and
`KeyReference` metadata. It cannot contain a PostgreSQL URL or raw HMAC/provider
credential. PostgreSQL credentials are resolved inside infrastructure and pool
replacement supports credential rotation without repository changes. Optional
OIDC/provider secret references use the same canonical provider.

Ephemeral secrets are development/test-only and rejected in homologation.
Readiness requires an external-provider-ready adapter, resolvable required
references and an active versioned pseudonymization key. Only reference,
version, actor, purpose, timestamp, policy and outcome may enter audit. Raw
values, credentials, HMAC material, tokens and private keys are prohibited from
PostgreSQL, APIs, metrics, logs and exception messages. See
`docs/SECRETS_KEY_MANAGEMENT.md`.
