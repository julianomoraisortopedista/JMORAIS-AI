# PROJECT STATE

## Project

JMORAIS-AI

## Mode

ULTRA LOW TOKEN EXECUTION MODE

## Current Sprint

S005 — Minimal Clinical Workspace UI

## Sprint Status

S005 = DONE — SOFTWARE BOUNDARY
S004 IMPLEMENTATION = COMPLETE
S004 FINAL VALIDATION = PASS
S004 = DONE
S003 remains DONE

## Approved Prerequisites

- Patient Context Exact Reference — PASS
- Clinical State Exact Reference — PASS
- Clinical State Timeline Reference — PASS
- Governed Evidence Exact Reference — PASS
- Governed LLM Draft Exact Reference — PASS
- Medical Document Exact Reference — PASS
- Human Review Exact Reference — PASS
- Clinical Reasoning Exact Upstream Lineage — PASS
- Clinical Reasoning Input Exact Reference — PASS
- Orthopedic → Clinical Reasoning Exact Lineage — PASS
- Audit Defense Exact Reference Resolution — PASS
- PGI → Defense Package Exact Reference Linkage — PASS
- Audit Defense In-Memory Exact Resolution — PASS
- Audit Defense Gateway Exact Resolution — PASS
- PostgreSQL Native SHA256 Checkpoint Fix — PASS
- Audit Defense persisted-reference cryptographic completeness — PASS
- Audit Defense PRE_LINK → STAGE11_LINKED exact reference — PASS
- Audit Defense → Medical Document exact Stage-11 lineage — PASS
- Clinical Workspace first read-only viewers — PASS
- Clinical Workspace remaining read-only viewers — PASS

## Current Checkpoint

PRODUCT RELEASE CLOSURE = DONE — 2026-10-01
SOFTWARE RELEASE CANDIDATE = PASS
LIVE INTERNAL PILOT READY = PENDING — EXTERNAL DEPLOYMENT CONFIGURATION

- Single repository-owned command: `make release-candidate`. All 19 stages PASS in `/tmp/release-candidate-final.log`; the command recreates the evidence without relying on that temporary log.
- PostgreSQL 16.14; Alembic current=head `068_offline_medical_dependencies`. Migration 067 retained; no synthetic lifecycle backfill.
- Lifecycle authority: 10 focused proofs PASS. Historical exact reference and read-only current projection are separate; revoked/withdrawn/superseded evidence fails closed. Restart, tenant isolation, NOBYPASSRLS, append-only, missing authority and deliberate tamper covered.
- Policy domains: 53 focused tests PASS. Authenticated IAM policy is independent of ST-02 Evidence and MIP-10.1 Gateway/Invocation; same authorized launch retains references unchanged. Owner-specific policy, provenance and integrity checks remain enforced.
- Cryptographic replay: 9 focused proofs PASS. Owner and offline verifier evidence valid; missing/tampered authority rejected. Migration 068 grants only SELECT on guideline/orthopedic exact-reference dependencies of Medical Document replay, with no verifier DML or API RLS changes.
- Backend/runtime: 6 focused proofs PASS, including actual production ASGI process over TLS, startup offline replay, liveness/readiness, same-origin static serving, authorized bootstrap, all seven exact viewers, wrong-principal/tenant and forged-reference rejection.
- Frontend production build, Node tests, typecheck and lint PASS. pip check, compileall, secret scan (zero findings), generated/private artifact check and git diff --check PASS. Scanner regression test PASS; annotations are distinguished from assigned credential values.
- First release-command run stopped at CRYPTOGRAPHIC_REPLAY/PERMISSION. Exact missing SELECT corrected; subsequent secret-scan false positives corrected without suppressing credential assignments.
- Operator instructions: `INTERNAL_PILOT_RUNBOOK.md`; configuration names: `config/internal-pilot.env.example`. Manual CI workflow invokes the same gate; remote CI was not executed.
- Existing S001–S005 accepted evidence retained. No historical full-suite rerun, new feature sprint, commit, push or merge.

### Unified platform — 2026-10-06

- Single web platform at http://localhost/ (apps/web): premium login + sidebar shell with Visão geral, Pacientes (unchanged launch/seven viewers), Evidências and Documento ao convênio.
- Evidence workbench mounted in the backend at /internal/evidence behind the existing IAM (OIDC bearer, CLINICAL_REVIEW, HUMAN CLINICAL_REVIEWER, no caller tenant/role headers); per-principal state; 30 s request budget kept (10 results per search).
- Fixed pre-existing defect: browser OIDC login failed with "Illegal invocation" (unbound fetch). Real-browser login verified.
- Evidence: release-candidate gate 19/19 PASS; local-pilot-proof LOCAL_PASS; 1134 passed with PostgreSQL; frontend 10 tests + typecheck + lint + build PASS; authenticated end-to-end search → Claude proposal → physician decision → document through the platform.

### Local synthetic pilot proof — 2026-10-05

- `make local-pilot-up` + `make local-pilot-proof` PASS: real Keycloak code+PKCE, 3 synthetic launches x 7 viewers, readiness, authorization denials, cryptographic replay VALID, runtime role NOBYPASSRLS. Synthetic data only; secrets live in `~/.local/share/jmorais-local-pilot` (0600), never in the repository.
- Root cause of the earlier bootstrap 403: the seed issued all three governed drafts from one fixture document, so drafts 2 and 3 correctly SUPERSEDED their predecessors and patient 1/2 launches failed closed ("governed draft lifecycle is not ACTIVE"). Fix: one pseudonymous `pt_` subject per synthetic patient. No authorization, signature or lifecycle validation changed.
- Full suite against isolated PostgreSQL 16: 1004 passed, 8 skipped; pilot production runtime test PASS on a migrated `pilot_release_*` database. Stale Alembic head pins (065/066) updated to `068_offline_medical_dependencies`; API identity-SDK guard now checks imports via AST instead of banning the OIDC scope string "openid".
- LIVE INTERNAL PILOT READY remains PENDING on external deployment prerequisites (DEPLOYMENT_PREREQUISITES.md).

### Deployment preparation — 2026-10-01

- Existing software release gate remains 19/19 PASS; no historical gate repeated.
- Operator wrappers added: pilot-check/up/status/down, explicit tenant-scoped physician link and owner-reference launch command. Existing production composition and IAM/owner services retained; no new persistence or infrastructure.
- Focused operator proof: 18 tests PASS (15 initial + 3 process lifecycle), compileall PASS, sensitive-data scan zero findings, diff check PASS. Process and transaction wrapper tests use controlled doubles; real external deployment/provisioning has NOT been executed.
- Single empty fail-closed template: config/internal-pilot.env.example. Runbook includes environment contract, identity/launch procedure, shutdown and recovery. DEPLOYMENT_PREREQUISITES.md consolidates external host/TLS/OIDC/provider/DB/IAM/clinical-owner inputs.
- Candidate list prepared at /tmp/jmorais-release-checkpoint-candidates.nul; no staging/commit authorization used. No commit/push/merge.
- LIVE INTERNAL PILOT READY remains PENDING. Next action: institutional owner supplies the approved deployment prerequisites through secure configuration, then execute real authenticated pilot acceptance. Checkpoint authorization is a separate decision.

S005 final software checkpoint — PASS (2026-09-27).

- OIDC public-client Authorization Code + PKCE S256 implemented with public runtime configuration, state/nonce checks, signed RS256 ID-token verification and callback URL cleanup. Access token remains in memory; a five-minute, single-use PKCE transaction survives redirect in sessionStorage without tokens, clinical data or launch references. Existing backend Bearer/IAM validation remains authoritative.
- Seven read-only Workspace viewers and authenticated shell implemented in `apps/web` using native ES modules. Complete owner-issued launch reference is imported as JSON and transported unchanged; no patient search, scalar reconstruction, clinical mutation or clinical browser persistence.
- Prospective ClinicalWorkspaceLaunch service validates stored references through approved exact viewers; same-principal/tenant/organization/purpose/policy authorization is mandatory. Bootstrap returns stored transports with secure errors/no-store. Homologation/production composition uses existing IAM and exact owners. No historical backfill.
- PostgreSQL focused evidence recovered from `/tmp/s005-launch-focused.log`: 21 passed, 1 existing Starlette/httpx warning, 8.85s. PostgreSQL 16.14; Alembic current == head == `066_workspace_launch` in the isolated test environment. No test rerun at closure.
- That run covers launch creation, authorized bootstrap to all seven S004 viewers, wrong principal/tenant/organization and forged-reference denials, RLS/NOBYPASSRLS, append-only rejection, fresh exact reread and tamper/deletion/missing-checkpoint detection through the existing replay engine. S004 API/runtime regressions included. No separate global replay or full backend suite claimed for S005.
- Retained local evidence: 7 frontend tests PASS; 10 launch unit tests + 5 API architecture tests PASS; TypeScript typecheck PASS; ESLint PASS. Development dependencies installed and pnpm lockfile present.
- Final production build PASS using the exact package.json build script (`node scripts/build.js`); pnpm wrapper stalled and was cancelled without dependency changes. Final git diff --check PASS. Generated dist/node_modules are ignored; no obvious secret, environment or diagnostic artifact in the candidate source paths.
- Integration evidence combines mocked standards-compliant browser OIDC/client tests with real PostgreSQL/authenticated HTTP launch/bootstrap/viewer tests. Real-browser automation is POST_RELEASE per the approved finalization scope; Playwright is not a dependency and was not required or executed. No real institutional IdP connection is claimed.
- EXTERNAL OIDC CLIENT REGISTRATION = PENDING. Real issuer/client_id/scopes/redirect registration and same-origin static/runtime deployment remain prerequisites for the internal pilot, not S005 software blockers.
- Earlier execution-environment blocks are resolved for the required gate. No commit/push/merge/reset/clean; no next milestone started.

### S004 completed checkpoint

S004 final milestone — PASS (2026-09-23). S004 DONE.

- Final isolated PostgreSQL 16 run: 958 passed, 8 skipped, 1 existing deprecation warning (40.55s); coverage 94.00417476426978% (required >=90%).
- Evidence: `/tmp/s004-final2-coverage.log`, `/tmp/s004-final2-coverage.json`.
- PostgreSQL 16.14; Alembic current == head `065_defense_reference_state`. No S004 migration.
- COMPLETE_CASE 1→14 and global cryptographic replay PASS within the final suite; no separate duplicate replay run. Production/homologation startup, authenticated caller/tenant boundary, exact-reference API architecture, RLS/read-only and restart proofs PASS in that suite.
- Replay diagnosis: shared test database contained an unrelated previously tampered Governed Evidence stream; clean isolated COMPLETE_CASE replay VALID (16 streams). Classification B-ISO; COMPLETE_CASE now creates and removes only its own isolated test database. No production cryptographic behavior changed.
- Original 20 failures resolved through obsolete test composition/detector corrections and test isolation. Shared explicit signing-key binding retained for issuance/read; exact domain class matching excludes transport names; only the seven approved read-only POST routes are allowed by the architecture test. Batch regression: 39 passed before the final suite.
- pip check, project compileall and git diff --check PASS. Existing Starlette/httpx deprecation warning deferred to POST_RELEASE.
- All S004 MUST_HAVE items complete. No UI implementation; no commit/push/merge/reset/clean.

### S004 Increment 3 approved checkpoint

S004 Increment 3 — Authenticated context + real runtime composition — PASS.
GOVERNED DRAFT SIGNING-KEY BLOCKER = RESOLVED (accepted prior evidence; not rerun).

- GET `/internal/api/v1/workspace/context` exposes only authenticated caller identity, authorized tenant/organization, role, operation purpose and effective WORKSPACE_READ permission. No session/token material.
- Workspace purpose is fixed to CLINICAL_REVIEW by the operation and authorized against existing IAM identity-link permissions; caller context overrides are rejected. Existing OIDC/session/tenant authentication is reused.
- compose_homologation now constructs both approved Workspaces with exact owner repositories over PostgreSQL read-only transactions; compose_production passes those same Workspaces into create_app. No repositories/SQL in routes, new persistence, migration, inferred references or mutation endpoints.
- Focused evidence: 4 real OIDC/runtime HTTP cases PASS across homologation/production and all seven viewers (including both Defense states), plus 11 directly affected API/architecture regressions PASS. RLS/NOBYPASSRLS/read-only owner queries, typed-reference round-trip, cross-tenant denial, secure context/errors/logs and startup composition verified. Existing signing-key tests were not repeated.
- Production's previously approved global startup replay gate was isolated in the focused test; no global replay or milestone gate was executed. Test client uses the existing allowed HTTPS host; duplicate no-store headers preserve the same cache policy.
- git diff --check: PASS.
- Documented S004 implementation MUST_HAVE checklist complete: seven viewers, authenticated context, runtime handoff, reuse of health/readiness, safe errors and focused boundary proofs. S004 final milestone validation remains PENDING. UI/S005 not started.

### Signing-key blocker resolved checkpoint

Governed Draft authoritative signing-key binding = RESOLVED.
Historical unbound drafts = FAIL-CLOSED / NO BACKFILL.

- Required explicit `InternalApiConfig.governed_draft_signing_key: KeyReference`; SIGNING_KEY only, distinct from pseudonymization identity, no default or generic-secret selection.
- Existing ManagedAttestationFactory binds the configured key to prospective issuance. Frozen draft JSON stores only provider/key_id/version/purpose; the draft integrity hash and HMAC cover that binding. Existing persisted exact reference binds it through draft_integrity_hash. No migration or historical mutation.
- Homologation exposes the managed issuance attestor and read-only exact repository; production reuses that canonical composition. Restart verifier resolves the persisted key only when equal to the explicitly authorized configuration and verifies managed-key metadata/state. Missing, wrong, unavailable or tampered bindings fail closed.
- Focused evidence: 28 distinct tests PASS across scoped runs (binding/restart/composition, managed attestation, issuance, exact-reference unit/PostgreSQL/architecture, production configuration and homologation). Production startup global replay was isolated in the composition test; no replay executed or newly claimed.
- PostgreSQL read-only/NOBYPASSRLS, cross-tenant/missing-context rejection, append-only UPDATE/DELETE rejection, signed historical unbound rejection and absence of secret material in payload/logs verified.
- Scope stops at signing-key handoff. Remaining S004 Increment 3 context/viewer runtime composition is not implemented here.

### S004 Increment 2 approved checkpoint

S004 Increment 2 — Remaining Workspace API viewers — PASS.

- Six read-only POST routes under `/internal/api/v1/workspace/`: timeline, evidence, explainability, medical-document, human-review and audit-defense, each ending `/resolve`.
- Full nested typed reference transport, with required fields and forbidden extra fields; no issuance, inferred versions or scalar trust. Existing owner exact reads remain authoritative; Timeline uses get_timeline_exact(reference).
- Shared tenant/error boundary, existing authenticated authorization with WORKSPACE_READ capability, no-store responses and sanitized validation/owner/internal errors. Workspace instances are explicitly injected into the API factory.
- Focused validation: 18 passed (S004 remaining API, S004 summary API and directly affected internal API tests), 1 existing FastAPI deprecation warning; PostgreSQL 16 backed. Cross-tenant/missing auth/context, malformed/forged references, altered Timeline order and mismatched Defense states rejected. No fallback or DML; read-only/NOBYPASSRLS and safe logs/errors checked.
- Audit Defense PRE_LINK / STAGE11_LINKED and linked document projection preserved; replay remains NOT_EVALUATED and completeness unknown. No migration or approved domain changes.
- Remaining S004 MUST_HAVE: authenticated user/active-tenant/permission context contract (or verified existing equivalent), runtime bootstrap composition of the injected viewers with approved read-only owners and demonstrated caller reference handoff, then final S004 milestone validation. Existing health/readiness infrastructure is reused, not duplicated.
- Decision: Increment 2 complete; S004 implementation remains IN PROGRESS. No UI/S005.

### S004 Increment 1 approved checkpoint

S004 Increment 1 — Clinical Summary API / exact-reference handoff — PASS.

- POST `/internal/api/v1/workspace/summary/resolve`: authenticated/authorized tenant → complete typed PersistedClinicalStateReference → injected approved ClinicalWorkspace → owner get_exact(reference).
- Existing API authentication, authorization and TenantContextBinder reused; missing context and cross-tenant requests fail closed. No reference issuance or scalar fallback.
- Secure ApiError mapping and no-store responses; malformed/forged references rejected without sensitive internals in errors/logs.
- Focused evidence: original run 9 passed / 1 failed (UTC JSON spelling Z versus +00:00 in test expectation); only that expectation corrected, typed reference round-trip preserved; affected test rerun 1 passed. Total 10 focused tests passed across these runs, including internal API regression and trust-path architecture.
- PostgreSQL-backed HTTP test uses existing owner-issued persisted reference and reader composition; SELECT/SET/SHOW only, read-only transactions, NOSUPERUSER/NOBYPASSRLS. Other viewer endpoints not implemented.
- API factory accepts an explicitly composed Workspace; production bootstrap wiring is not claimed by this increment. No migrations or frozen-domain changes.

### S003 completed checkpoint

S003 final validation gate — PASS (2026-09-21).

Most recent migration (unchanged):

`065_defense_reference_state`

Timeline, Medical Document, Human Review and Audit Defense viewers compose immutable metadata through existing owner-approved exact query ports. Timeline uses only `get_timeline_exact(reference)` and preserves owner-controlled member ordering. Other viewers use `get_exact(reference)`; STAGE11_LINKED also rereads its exact Medical Document reference. PRE_LINK remains explicitly unlinked. Source references retain version, predecessor, tenant, provenance/integrity and traceability metadata. Replay is explicitly NOT_EVALUATED and completeness is unknown: an exact read is not a replay attestation. No clinical mutations, new trust contracts, frozen-module changes, frontend or API.

Focused validation: 15 tests passed (1 architecture/source-hygiene, 14 PostgreSQL integration cases). PostgreSQL 16: Alembic current == head (`065_defense_reference_state`). Same-tenant reads pass; cross-tenant/missing TenantContext, invalid references/hashes, reordered timeline references and deleted persisted references fail closed. Missing timeline member, Stage-11 document and governed draft dependencies also fail closed; all deletion probes rolled back. Reader transactions are read-only, NOSUPERUSER and NOBYPASSRLS, with no DML in monitored viewer queries. CLINICAL_WORKSPACE_REMAINING_VIEWERS_EXACT_REREAD = PASS after disposal and fresh reader/owner/workspace composition; results are deterministically equivalent. Focused source hygiene, compileall and `git diff --check`: PASS. This focused checkpoint preceded the final gate recorded below.

## S003 Final Gate Evidence (historical)

- Full pytest: 942 passed, 8 skipped, 1 deprecation warning; final run 36.85s.
- Coverage: 93.85670618057108% (12,589 / 13,413 statements), above 90%.
- Evidence: `/tmp/s003-final-coverage.log`, `/tmp/s003-final-coverage.json`.
- PostgreSQL 16 / Alembic current == head: `065_defense_reference_state` — PASS.
- COMPLETE_CASE 1→14, global replay, RLS/restart: PASS; accepted existing evidence retained without repeating expensive validations.
- Read-only architecture / exact trust paths: PASS through approved focused checks and final suite.
- pip check: PASS from existing gate evidence.
- source hygiene, compileall (jmoraIs/evaluation/tests), git diff --check: PASS, refreshed at closure.
- S004 not implemented. Release planning: `RELEASE_FINISH_PLAN.md`.

## Current Blocker

None in the validated software release candidate. Real external OIDC registration,
approved managed runtime configuration/TLS, identity/tenant provisioning and deployment
remain external prerequisites; live pilot readiness is not claimed.

## Next Action

Configure the external deployment prerequisites using INTERNAL_PILOT_RUNBOOK.md,
then require `make release-candidate` PASS before opening the authorized internal pilot.
No S006 or new backend/UI functionality is authorized.

## Frozen / Approved

Do not re-audit unless directly affected:

- Patient Context
- Clinical State
- Terminology
- Evidence Engine
- Clinical Appraisal
- Governed Evidence
- Clinical Reasoning
- Guideline Engine
- Orthopedic Intelligence
- Medical Document
- Audit Defense reasoning semantics
- LLM Gateway
- Governed LLM Draft
- Human Review
- FHIR MVP
- SMART on FHIR
- Runtime Security
- Supply Chain Security
- RC1
- RC2

## Permanent Trust Rules

Always:

- owner-issued references
- `get_exact(reference)`
- fail-closed
- restart-safe
- append-only
- RLS
- cryptographic replay
- checkpoint completeness
- Human Review

Never use as trust source:

- `latest()`
- `history()`
- `at()`
- free scalar IDs
- inferred versions
- retained process-local objects
- synthetic backfill
- validation-only trust wrappers

## Validation Policy

During prerequisites:

- focused unit tests only
- focused architecture tests only
- focused PostgreSQL tests when required
- no full pytest
- no COMPLETE_CASE
- no RC1/RC2 benchmarks

At S003 completion only:

- PostgreSQL 16
- Alembic current/head
- full pytest
- coverage >= 90%
- COMPLETE_CASE 1→14
- global replay
- restart
- RLS
- pip check
- git diff --check
- source hygiene
- compileall

## Repository Safety

Do not:

- commit
- push
- merge
- reset
- checkout destructively
- discard uncommitted S003 work

## State Update Policy

After each prerequisite:
update only:

- last approved item
- current blocker
- next action

Do not reconstruct historical project state.
