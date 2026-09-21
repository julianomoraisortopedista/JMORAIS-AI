# Production Composition

Production composition consumes the canonical package version from `jmoraIs.__version__` and verified build metadata. The supply-chain verifier runs before deployment composition; HTTP handlers and runtime database roles have no access to signing, SBOM generation or release-evidence mutation.

The production profile is an explicit engineering deployment boundary. It does not authorize patient care, autonomous decisions, regulatory claims or public API exposure.

The canonical trust chain is PostgreSQL 16/current Alembic head → safe runtime role/RLS → managed secrets and pseudonymization key → OIDC/JWKS → identity and tenant → durable session/JTI validation → purpose and authorization → governed read-only API. Reviewer governance, canonical repositories, append-only audit, external metrics, JSON logging and cryptographic replay are mandatory.

`compose_production` has no development fallback. It rejects development authentication, ephemeral secrets, in-memory observability, stale migrations, unsafe database roles, missing RLS/triggers, unavailable governance dependencies and tampered replay. `jmoraIs.api.production_asgi:create` accepts only an explicitly injected external composition factory.

Startup independently validates database connectivity, the single canonical Alembic
head (`051_patient_context_exact_ref` for this release), runtime
`jmorais_application_writer` with `NOBYPASSRLS`, tenant policies, append-only
triggers, managed references, IAM/JWKS, session security, repositories, audit,
metrics and full cryptographic replay. Deployment audit and build metadata use the
same schema-revision constant, preventing a stale schema from being reported as
current. Safe deployment metadata is appended without secret values.

Before request traffic, production resolves a distinct offline-replay credential,
creates an isolated verifier pool, executes global replay, records safe audit
metadata and disposes the pool. The API composition retains neither verifier,
engine nor credential. Runtime readiness no longer attempts global replay through
the tenant-scoped API role.

Shutdown flushes audit/metrics/log adapters when supported and disposes the database pool. Deployment orchestration must stop new traffic before the configured grace period expires.

RC2 capacity rules are documented in `PERFORMANCE_ENGINEERING.md`, `CAPACITY_MODEL.md` and `SCALABILITY.md`. Worker count is deployment-derived; aggregate pool capacity includes every worker, the isolated verifier and an administrative reserve. Admission remains bounded. Tuning may not disable RLS, exact reread, audit, replay, append-only guarantees or Human Review.

FastAPI lifecycle management uses a lifespan context; deprecated `on_event` hooks are not used by production composition. `RuntimeSecurityMiddleware` wraps production admission. PostgreSQL connections have explicit pool, acquisition/connect, statement, lock and idle-transaction bounds, an application name and mandatory production TLS. Offline replay retains its independent one-connection pool and credential.

The internal `/build` endpoint exposes release ID, build ID, source revision, timestamp, Python version and migration revision only. It requires normal internal authentication and contains no secrets or provider payload.
