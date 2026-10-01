# RELEASE_FINISH_PLAN

S003 DONE — 2026-09-21. S004 DONE — 2026-09-23. S005 DONE — SOFTWARE BOUNDARY — 2026-09-27.

| Etapa | Classificação | Entrega necessária |
|---|---|---|
| S004 — API / Presentation Boundary | MUST_HAVE | DONE: sete viewers, contexto autenticado e composição exata; gate final aprovado. |
| Minimal Clinical Workspace UI | MUST_HAVE | DONE — SOFTWARE BOUNDARY: sete viewers, OIDC público/PKCE e bootstrap exato validados. |
| Autenticação / integração local interna | MUST_HAVE | Contrato de software DONE; registro externo do cliente OIDC e valores reais de runtime PENDING. |
| Packaging / runtime configuration | MUST_HAVE | DONE: comando único, runbook e template público; valores reais de implantação pendentes. |
| Validação final de release | MUST_HAVE | DONE: make release-candidate PASS em ambiente NON-LIVE, incluindo processo real e sete viewers. |
| Pré-requisitos de produção institucional | POST_RELEASE | Planejamento separado de operação, integração e governança institucional; obrigatório antes dessa implantação. |
| Melhorias opcionais | POST_RELEASE | Fora do escopo mínimo de fechamento. |

NEXT SINGLE ACTION: Configure external deployment prerequisites through INTERNAL_PILOT_RUNBOOK.md.

## S005 closure

DONE — SOFTWARE BOUNDARY. All defined software gates PASS; evidence in PROJECT_STATE.md.
No Playwright dependency or new browser E2E framework. Browser automation remains
POST_RELEASE under the approved finalization scope. Existing Starlette/httpx and
ESLint development-tool deprecation notices remain POST_RELEASE maintenance.

EXTERNAL OIDC CLIENT REGISTRATION = PENDING. Before the internal pilot, configure
the real public client, issuer, scopes, registered redirect and provider browser
exchange support; serve static UI/config/callback and API on the approved origin.
No secrets belong in public configuration. Provide a legitimate prospective launch
through the authorized application producer. Do not fabricate clinical references.
These are deployment prerequisites, not unfinished S005 source requirements.

Product Release Closure: DONE — 2026-10-01. SOFTWARE RELEASE CANDIDATE = PASS.
LIVE INTERNAL PILOT READY = PENDING — EXTERNAL DEPLOYMENT CONFIGURATION.
The manual CI workflow calls the same `make release-candidate` gate; remote CI execution remains unclaimed.

## S004 planning — API / Presentation Boundary

Status: DONE — 2026-09-23. Planning baseline: `f36f25c0abaf60e9819e247e3bd8c1d08705062e`.
All documented S004 MUST_HAVE items implemented and validated; the plan below is
retained as the accepted scope. Final gate: 958 passed, 8 skipped; coverage
94.00417476426978%. PostgreSQL 16.14/current=head `065_defense_reference_state`;
COMPLETE_CASE, replay, runtime, auth/RLS/exact references and hygiene PASS.
Evidence: PROJECT_STATE.md. Existing Starlette/httpx warning: POST_RELEASE.

### Objective / IN SCOPE — MUST_HAVE

Expose the seven approved read-only Workspace viewers through the existing
FastAPI application/runtime and authenticated application boundary. Reuse current
security dependencies, exact owner ports and viewer DTOs; add only transport,
authorization composition and safe error mapping necessary for the future UI.
Existing file names establish reuse targets, not verified route signatures.
Confirm only those signatures during the first implementation increment.

### Minimum endpoint inventory — MUST_HAVE

Proposed routes below are read queries using POST bodies to avoid putting exact
reference payloads into URLs/access logs. POST must not imply domain mutation.
Reuse equivalent existing routes where available; do not add duplicate routes.

| Proposed contract | Input | Output |
|---|---|---|
| POST /workspace/summary/resolve | Typed exact references required by the approved summary viewer | Existing clinical summary projection |
| POST /workspace/timeline/resolve | Persisted timeline reference | Approved ordered timeline projection |
| POST /workspace/evidence/resolve | Exact reference(s) accepted by evidence viewer | Approved evidence projection |
| POST /workspace/explainability/resolve | Exact reference(s) accepted by explainability viewer | Approved explainability projection |
| POST /workspace/medical-document/resolve | PersistedMedicalDocumentVersionReference | Approved document projection |
| POST /workspace/human-review/resolve | PersistedHumanReviewReference | Approved review projection; no decision command |
| POST /workspace/audit-defense/resolve | PersistedDefensePackageReference | Approved defense projection and existing linkage state |
| GET /workspace/context (or existing equivalent) | Existing authenticated session | Minimum user identity, authorized active tenant and effective workspace permissions |
| Existing health/readiness routes, if supported | Existing operational contract | Existing safe liveness/readiness result |

Tenant context is part of the authenticated context contract, not a new endpoint
or authority derived from arbitrary request headers. Health/readiness reuse their
existing exposure policy; do not disclose database, credentials or internals.

### Request / response and exact-reference transport — MUST_HAVE

Use explicit bounded schemas matching existing owner reference types and approved
viewer inputs; reject extra fields, wrong reference kinds and malformed payloads.
Transport the full existing owner-issued reference losslessly (including exact
version, tenant, policy, integrity and lineage fields required by its contract).
Do not issue, infer, sign anew or reconstruct references from free scalar IDs.
Decoding produces untrusted typed input; only the owner exact port validates trust.
References confer no authorization by themselves.

The caller obtains references from existing authorized owner/application outputs;
returned approved references may support subsequent viewer reads. No discovery,
latest-record fallback or synthetic bootstrap endpoint. Before implementation,
confirm the existing caller handoff supplies every required reference; if missing,
report that concrete integration blocker before expanding scope.

Return explicit response DTOs mapped from approved viewer projections only;
no ORM/repository objects or additional clinical reasoning. Preserve source
references, exact version/order and existing PRE_LINK/STAGE11_LINKED semantics.
Timeline uses get_timeline_exact(reference); other owners use get_exact(reference).
Do not convert exact reads into replay attestations: preserve NOT_EVALUATED and
unknown completeness where applicable. Reuse existing API versioning conventions.

### Authorization / read-only enforcement — MUST_HAVE

Presentation → existing authentication/authorization application boundary →
approved Workspace services/ports → owner-issued references → exact owner reads.
Authenticate and authorize the requested operation and tenant before reading.
Missing/invalid session or TenantContext fails closed. Validate reference tenant
against authorized context; retain database RLS and reader NOBYPASSRLS/read-only
transactions through existing composition. Presentation receives no repository,
SQL connection or verifier capability. Retain applicable SMART/IAM controls; no new
login, token issuance, role model or institutional identity design.

No clinical writes, reference issuance, generation, review decisions or repair
from Workspace routes. Existing approved metadata-only security telemetry may
remain. Use no-store responses and existing transport protections. Do not log
request/response bodies, clinical payloads, references, tokens or secrets; retain
only approved operational metadata and safe correlation identifiers.

### Error model — MUST_HAVE

Reuse the current envelope if available; otherwise one minimal envelope:
`error: {code, message, correlation_id}`. Codes/messages are stable and sanitized.
Map malformed contracts to 422, absent/invalid authentication to 401, denied
operation/context to 403, unavailable authorized resources to 404, rejected exact
integrity/lineage to a safe conflict response (409), and unavailable dependencies
to 503. Tenant denials must not reveal resource existence. Unexpected failures
return generic 500. Never echo supplied secrets, references, clinical values,
SQL errors or stack traces, including framework validation errors. Existing secure
error conventions take precedence over these proposed mappings.

### Minimal tests / acceptance criteria — MUST_HAVE

During implementation only:
- Focused API contracts for all seven projections and authenticated context;
  deterministic output identical to the approved viewer result.
- Missing session/context, denied permission, cross-tenant reference, malformed or
  fabricated reference, wrong kind/version and integrity/lineage rejection fail
  closed; no fallback lookups or resource-existence disclosure.
- Focused architecture test: presentation depends on approved application ports,
  no direct repository/database or history/latest/at/scalar trust reconstruction.
- Focused PostgreSQL composition proof: same-tenant exact reads after fresh runtime,
  cross-tenant blocked, read-only/NOBYPASSRLS preserved and no clinical DML.
- Safe errors/logs and no-store responses; existing health/readiness regression
  only if the route composition changes.
No frozen-module audit; reuse accepted dependency evidence. Run only tests needed
for the new boundary and directly affected composition.

### Definition of DONE — MUST_HAVE

All seven routes (or existing equivalents) and context are usable with existing
owner-issued references; authenticated UI handoff is demonstrated. Focused tests
above pass, safe errors and read-only/RLS behavior are evidenced, and existing
runtime routes remain compatible. Update completion controls only after evidence;
S003 dependencies remain approved. No frontend is required for S004 DONE.

### OUT OF SCOPE — POST_RELEASE relative to S004

UI implementation (separate MUST_HAVE release step), new reasoning/generation or
mutation endpoints, search/discovery, bulk export, streaming, custom caching,
new replay endpoints, new trust/reference stores and optional API enhancements.
Institutional IAM/KMS/HA, hospital rollout and infrastructure redesign remain
separate institutional prerequisites, not S004 deliverables. Classification here
does not waive requirements before institutional deployment.

### Implementation order — MUST_HAVE

1. Confirm existing route/security signatures and reference handoff narrowly;
   fix endpoint/schema names around existing contracts without reopening domains.
2. Define transport DTOs and safe error mapping in the existing API boundary.
3. Compose authorization/context and one exact viewer vertical slice.
4. Add the remaining six viewer mappings with the same approved composition.
5. Execute focused contract/architecture/PostgreSQL checks and record S004 evidence.

Estimated scope: seven thin query mappings plus one context contract, reused
health/readiness, a small transport/error/composition layer and focused tests.
No planned migration, domain change, new infrastructure or UI.

NEXT SINGLE ACTION: MINIMAL CLINICAL WORKSPACE UI planning. Do not start another backend feature.

## External deployment handoff — 2026-10-01

Software RC remains PASS (19/19 accepted stages). Operator preparation is available:
`make pilot-check`, `pilot-up`, `pilot-status`, `pilot-down`, explicit identity and
launch commands. 18 focused wrapper tests PASS; no real provider/tenant provisioning
claimed. Use INTERNAL_PILOT_RUNBOOK.md and the single config template.
LIVE acceptance remains pending only the concrete deployment inputs and real
acceptance in DEPLOYMENT_PREREQUISITES.md. No S006, extra features or new infrastructure.
The explicit Git candidate is prepared but neither staged nor committed.
