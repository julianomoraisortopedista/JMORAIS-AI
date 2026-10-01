# Internal pilot operation

`make release-candidate` is the single NON-LIVE software acceptance command.
A PASS is required before deployment. It does not register an external OIDC client
or authorize use of live clinical data. No CI completion is claimed by local PASS.

## Prepare and validate software

1. Install Python 3.12, Node >=22, pnpm 10.17.1 and Docker with Compose.
2. Run `make setup` and `pnpm --dir apps/web install --frozen-lockfile`.
3. Run `make release-candidate` at the repository root.

The gate starts the existing PostgreSQL 16 test service and waits for health,
creates fresh `pilot_release_…` databases, applies Alembic to head, and only then
allows the test backend to start. It never migrates the configured base database.
No database is dropped automatically. The Compose test database uses deliberately
public test credentials and must never contain live data or become a deployment.
The optional `JMORAIS_TEST_POSTGRES_URL` is restricted to the local `jmorais_test`
database; otherwise the gate discovers the existing Compose test service.

The summary reports each stage, FIRST_FAILURE, a sanitized classification and one
next action. Any failure, missing proof or skipped required test blocks PASS.
The isolated TLS/JWT fixtures exercise actual production composition without a
real external identity provider. Full historical suites and benchmarks are not
part of this gate. CI calls exactly the same command through the manual
`software-release-candidate` workflow.

## Separate configuration responsibilities

| Configuration | Location and owner |
|---|---|
| Software | Python/Node dependencies, built `apps/web/dist`, current Alembic head |
| Public OIDC | Issuer, public client ID, registered redirect, scopes; no secrets |
| Server secrets | Existing managed provider and authorized versioned KeyReferences; never files in Git |
| Deployment | TLS certificate/key paths, approved origin/hosts, database TLS, external OIDC registration, identity/tenant provisioning, durable observability |

Use `config/internal-pilot.env.example` as names-only configuration guidance. Do
not source it as a working deployment: the composition factory is institution
specific. It must return the existing `compose_production` result with approved
managed secrets, explicit governed-draft SIGNING_KEY and pseudonymization key,
offline read-only verifier credential, IAM/tenant configuration and production
observability. Never use `tests.pilot_runtime_factory` outside NON-LIVE validation.

## Deploy/open only after software PASS and external prerequisites

1. Provision PostgreSQL 16 and approved managed configuration; require TLS and
   least privilege. Apply migrations with the migration identity and confirm
   `alembic current` equals `alembic heads` before backend startup.
2. Build with `pnpm --dir apps/web build`. From `apps/web`, run
   `python3 scripts/runtime-config.py` with approved public OIDC environment values.
3. Set `JMORAIS_WEB_DIST` to the absolute built directory and
   `JMORAIS_PRODUCTION_COMPOSITION_FACTORY` to the approved `module:callable`.
4. Start `.venv/bin/python -m uvicorn jmoraIs.api.production_asgi:create --factory
   --host 127.0.0.1 --port 8080 --ssl-certfile <certificate-path>
   --ssl-keyfile <private-key-path> --no-access-log --no-server-header`.
   Use approved deployment paths/host binding; do not commit key material.
5. Require `/internal/api/v1/health/live` and authenticated
   `/internal/api/v1/health/ready` to pass. Readiness requires an authorized
   operations caller and purpose; do not paste bearer tokens into shell history.
6. Open the approved HTTPS origin, authenticate through the real public OIDC
   client (Authorization Code + PKCE), and import an owner-issued prospective
   ClinicalWorkspaceLaunch reference JSON through the existing UI.
7. Verify Clinical Summary, Timeline, Evidence, Explainability, Medical Document,
   Human Review and Audit Defense. There is no patient search or mutation UI.

The trusted application producer issues the launch only after authenticating and
authorizing its principal and resolving the unchanged owner references. Operators
must not assemble references from scalar identifiers or alter their policies.
Scientific ST-02 and Gateway MIP-10.1 remain distinct from IAM policy.

## Lifecycle and historical data

Immutable lifecycle events provide historical provenance. The owner-maintained
current projection establishes present eligibility; its checkpoint and exact event
must agree. Revoked/withdrawn/superseded or missing authority remains fail-closed.
Migration 067 does not backfill historical references or current pointers. Normal
prospective owner transitions establish new authority. Historical unbound drafts
likewise remain fail-closed. Never repair provenance by UPDATE or re-signing.

## Shutdown and diagnosis

Stop only the backend process you started (Ctrl-C/SIGTERM). For NON-LIVE Compose,
`docker compose -f docker-compose.postgres-test.yml stop postgres-test` stops the
service; never use reset/clean/down-volume operations on live data. Temporary test
databases are disposable NON-LIVE evidence and are not automatically deleted.

- PERMISSION: inspect the named offline replay dependency; allow only demonstrated
  SELECT, never writes, superuser or broader API RLS access.
- CRYPTOGRAPHIC/RLS/SECURITY: fail closed. Investigate the first exact mismatch;
  never skip a family, disable verification or weaken an invariant.
- FIXTURE: correct only the isolated fixture or composition, then its focused test.
- Missing public OIDC configuration returns a safe unavailable response; configure
  the real issuer/client/redirect before live pilot use.

Real OIDC/provider/runtime configuration is an external deployment prerequisite.
Until configured, LIVE INTERNAL PILOT READY remains PENDING.

## Minimal live deployment inventory

MUST_HAVE: one approved host, PostgreSQL 16 with TLS and existing least-privilege
roles, the existing production ASGI factory, built same-origin UI, approved HTTPS
origin/certificate, real public OIDC client, managed-secret provider, durable
metadata-only observability, active tenant/organization and authorized identities.
No test factory, local test credentials or test database may supply live service.
POST_RELEASE: HA, clustering, institutional KMS design, autoscaling, additional
features and UI workflows. They are not introduced by this preparation.

The single template is `config/internal-pilot.env.example`. Required entries are
empty deliberately. Store actual configuration outside Git. Its environment names
are consumed by the existing runtime or the small operator wrappers:

| Names | Purpose/source | Secret? | Required | Format |
|---|---|---|---|---|
| JMORAIS_PRODUCTION_COMPOSITION_FACTORY | Deployment owner's approved factory | No | Yes | module:callable |
| JMORAIS_WEB_DIST | Operator's production build | No | Yes | absolute directory |
| JMORAIS_PILOT_ORIGIN / JMORAIS_PILOT_PORT | Approved HTTPS origin/local listener | No | Yes | https origin / 1024–65535 |
| JMORAIS_PILOT_TLS_CERT / JMORAIS_PILOT_TLS_KEY | Certificate authority/operator | Key contents: yes | Yes | absolute external paths; key mode 0600 |
| JMORAIS_PILOT_STATE_DIR | Operator private process record | No | Yes | external directory mode 0700 |
| JMORAIS_PILOT_CA_FILE | Approved private CA bundle if needed | No | Optional | absolute path |
| JMORAIS_WEB_ENVIRONMENT | Browser deployment mode | No | Yes | PRODUCTION |
| JMORAIS_WEB_OIDC_ISSUER / JMORAIS_WEB_OIDC_CLIENT_ID | Real public OIDC registration | No | Yes | issuer URL / client identifier |
| JMORAIS_WEB_OIDC_REDIRECT_URI / JMORAIS_WEB_OIDC_SCOPES | Registered same-origin callback and approved scopes | No | Yes | HTTPS URL / space-separated scopes |

The factory's existing `production_config` supplies OIDC provider/discovery/JWKS,
audience, algorithms, role/organization claims and mapping, IAM policy, explicit
SIGNING_KEY reference, separate pseudonymization reference, managed database and
offline-verifier credential references, build metadata, allowed hosts and durable
observers. Reference identifiers are metadata; resolved secrets remain server-side.
This template does not invent a second mapping for managed-provider configuration.
A deployment-owned factory/provider implementation and its configuration must be
supplied and verified before LIVE startup; the test factory is not that handoff.

## Operator commands

After approved configuration, migration and frontend build/config generation:

```sh
make pilot-check
make pilot-up
make pilot-status
make pilot-down
```

`up` starts only the existing production ASGI process, on loopback with TLS;
it neither provisions nor migrates PostgreSQL. Public reachability therefore
requires the approved host's existing routing to this listener. No proxy is
installed or trusted automatically. Runtime allowed-host/proxy configuration must
match the real deployment. `status` verifies TLS, liveness, same-origin UI and
operations-authenticated readiness including PostgreSQL and migration checks.
Tokens are requested without terminal echo and remain in memory. For approved
credential brokers, `PILOT_FLAGS=--token-stdin` accepts a pipe, never a token in an
argument. Do not put tokens in shell history, files, environment or command output.

`down` checks the private PID/start/command fingerprint and sends SIGTERM only to
that process. It never force-kills or deletes databases. Preserve configured TLS
files and UI configuration until shutdown; configuration validation also applies
to `down`. Stale process records fail closed and require operator investigation.
Application stdout/access logs are suppressed; approved production observers must
provide durable sanitized operational evidence.

## Explicit physician provisioning and first launch

An existing authenticated HUMAN administrator with ADMINISTRATION purpose and an
already ACTIVE tenant is required. Initial organization/tenant/administrator
bootstrap is an institutional prerequisite, not a new universal administrator.
Have the IdP administrator assign the physician's approved clinical reviewer role.
Create a private external metadata JSON containing exactly `provider`,
`external_subject`, `principal_id`, `organization_id`, `tenant_id`, `policy_version`.
The latter three must equal the authenticated administrator's existing context.

```sh
make pilot-link-physician PILOT_FLAGS='--input /approved/private/identity.json'
```

This uses existing IdentityLinkService and repositories, binds tenant context,
and commits identity plus audit in one transaction. Audit failure rolls back the
link. It grants only CLINICAL_REVIEW / api:read, creates no clinical data and does
not create an administrator. Duplicate identities fail rather than overwrite.

For the first usable case, the approved clinical owner pipeline must already issue
all seven typed references with legitimate prospective provenance. Export their
unchanged transport into a private `LaunchReferences` JSON: summary, timeline,
evidence, explainability, medical_document, human_review, audit_defense. Obtain
these from their owners; never assemble them from IDs or substitute policy values.
Authenticate as the intended physician with CLINICAL_REVIEW:

```sh
make pilot-create-launch PILOT_FLAGS='--input /approved/private/references.json --output /approved/private/launch.json'
```

The command calls the existing launch producer under authenticated tenant context;
it validates references through approved ports. Output is new, exclusive, mode0600
and outside the repository. A launch is principal-bound: import it in the browser
while authenticated as that same physician. Optional/missing viewer references do
not constitute seven-viewer pilot acceptance. No claim of real launch success is
made until this procedure runs against authorized real owners.

## Live acceptance and recovery

Record metadata-only evidence for: configuration/factory ownership; migration head;
TLS/hostname; real OIDC login and wrong-user denial; authenticated status; same-origin
UI; legitimate launch/bootstrap; all seven viewers; wrong tenant/reference denial;
RLS and read-only behavior; durable audit; controlled shutdown/restart.
The accepted NON-LIVE 19-stage gate is reusable evidence, not evidence of real IdP
registration or patient availability. Operator-wrapper focused tests are additional
NON-LIVE proof, not a second live rehearsal.

Before live data, the database owner must demonstrate encrypted backup and restore
into an isolated authorized environment using existing DBA procedures, with tenant,
append-only and cryptographic verification after restore. Do not restore over the
live database, rewrite provenance or generate replacement signing keys. Retain
original authorized key versions through managed retention. On readiness/replay
failure, stop admission and investigate the first exact failure; never bypass it.
