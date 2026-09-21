# Offline Replay Verifier Architecture

Status: implemented RC1 security boundary
Scope: operational integrity verification only

## Architecture proposed

`OfflineReplayVerifier` is an isolated operational composition, not a bounded
context and not an application capability exposed to clinical or scientific
workflows. It owns no medical policy, persistence model or replay algorithm.

The composition orchestrates the existing
`PostgreSQLCryptographicReplayEngine` through a short-lived PostgreSQL connection
with authorized global read visibility. The replay engine remains the sole
implementation of cryptographic reconstruction, completeness verification and
tamper classification. Duplicating or wrapping its rules would create a second
integrity truth and is prohibited.

No new domain port is required. The separation is operational: a dedicated
composition factory or command entry point constructs the existing engine,
executes it and returns only a structured integrity decision. A narrow
infrastructure-level callable may define the lifecycle, audit and cleanup
protocol, but it must not become a general repository or query port.

The API runtime remains tenant-scoped, `NOBYPASSRLS` and technically incapable
of global replay. Its dependency container must not contain verifier factories,
global database engines, verifier credentials or privileged connection handles.

## Responsibilities

The verifier is responsible only for:

- establishing an independently authenticated verifier session;
- confirming the expected database identity and PostgreSQL role;
- proving that the role is read-only and authorized for global integrity reads;
- executing `PostgreSQLCryptographicReplayEngine.replay_all()`;
- requiring a binary `VALID` or `TAMPERED` decision;
- recording metadata-only start, completion or failure audit events;
- closing the transaction, disposing the pool and releasing secret material;
- failing startup or release promotion when verification is not `VALID`.

It must not repair history, mutate checkpoints, issue packages, serve repository
queries, resolve tenant data for callers or return event payloads in its external
result.

## Trust boundaries

```text
Release/startup controller
        |
        | one authorized verification request
        v
Secrets/KMS boundary
        |
        | short-lived verifier credential
        v
Dedicated verifier pool
        |
        | SET ROLE jmorais_offline_replay_verifier
        v
PostgreSQL global read-only integrity view
        |
        v
PostgreSQLCryptographicReplayEngine
        |
        v
VALID | TAMPERED + metadata-only report
        |
        v
Append-only verifier execution audit
        |
        v
pool disposal and credential release
```

The verifier trusts PostgreSQL authentication, the expected database identity,
the managed credential reference and the deployed replay-engine build. It does
not trust stored hashes, stored payloads, event order, checkpoints or stream
completeness; those are independently verified by the existing replay engine.

## Execution flow

1. An approved startup controller, release job or disaster-recovery job requests
   verification with release ID, build ID, reason and correlation ID.
2. The process resolves a dedicated credential through the existing Secrets/KMS
   boundary. Raw credential material never enters logs, reports or application
   DTOs.
3. A new pool is created exclusively for this execution.
4. Before replay, the composition verifies the database identity, current
   Alembic head, exact role name, read-only transaction policy and expected
   privilege posture.
5. A read-only, repeatable-read transaction is opened. The transaction provides
   one coherent database snapshot for checkpoint and event reconstruction.
6. The existing replay engine performs global replay without tenant filtering.
7. The composition maps the result to `VALID` or `TAMPERED`. Exceptions,
   incomplete visibility or unverifiable streams map to failure, never `VALID`.
8. A metadata-only audit event is appended through a separately controlled audit
   capability. The event records no clinical or scientific payload.
9. The transaction ends, the pool is disposed and secret callback scope ends.
10. The caller receives only decision, counts, failed stream identifiers,
    timestamps, release/build identity and policy versions.

Startup verification must finish before HTTP traffic is enabled. The verifier
does not remain resident after readiness is established. Periodic checks, if
required, run as independent jobs rather than inside API workers.

## PostgreSQL roles and credentials

Use a dedicated role such as `jmorais_offline_replay_verifier` with these
properties:

- `NOLOGIN`; authentication occurs through a separately provisioned login role
  that may assume only the verifier role;
- no ownership of schemas, tables, functions or sequences;
- no `CREATE`, `INSERT`, `UPDATE`, `DELETE`, `TRUNCATE`, `REFERENCES`, `TRIGGER`
  or function-execution privilege beyond the minimum connection setup;
- `default_transaction_read_only = on`;
- explicit `SELECT` only on the tables required by the canonical replay registry;
- no access to direct-identity vaults, raw provider payloads or unrelated tables;
- no membership in API runtime, migration-owner or administrative roles;
- connection limit and statement/lock/idle-transaction timeouts;
- distinct `application_name` for database monitoring and audit correlation.

The credential must be independent from API runtime and migration credentials.
It must be short-lived where the provider supports dynamic credentials. Static
long-lived passwords are not acceptable for production readiness.

## RLS policy

The API runtime remains `NOBYPASSRLS`. Global replay must never be achieved by
weakening tenant policies, accepting a wildcard tenant or looping through
caller-visible tenants.

Recommended implementation uses a narrowly governed verifier role with
`BYPASSRLS` solely because PostgreSQL has no built-in read-all RLS capability
that is simultaneously independent of every tenant policy. This privilege is
acceptable only with all compensating controls in this document: read-only
transactions, explicit table grants, no ownership, isolated credentials,
non-resident pool, no HTTP reachability and complete execution audit.

An alternative is to add verifier-specific `SELECT` policies to every
tenant-scoped replay table. That avoids `BYPASSRLS` but expands the policy surface,
couples every future stream migration to a special role and increases the chance
of incomplete replay. It is not recommended for RC1.

## KMS and credential policy

- Store only an opaque verifier credential reference in configuration.
- Resolve it through the existing Secrets/KMS callback boundary.
- Separate verifier, runtime and migration key/credential purposes.
- Require active key version and fail closed on retired, revoked or unavailable
  material.
- Prefer dynamic database credentials with a validity window bounded to the job.
- Audit secret resolution by reference, purpose, version, actor and outcome;
  never record secret bytes or connection URLs.
- Rotation must overlap only long enough to complete an active verification;
  new executions use the new active version.
- Emergency revocation must prevent new pools and terminate existing verifier
  sessions operationally.

## Lifecycle and resource disposal

The verifier has a one-execution lifecycle:

```text
NOT_CREATED -> CREDENTIAL_RESOLVED -> CONNECTED -> VERIFIED | FAILED -> DISPOSED
```

There is no reusable singleton and no pool shared with API workers. Disposal is
mandatory in a `finally` path for success, tamper, timeout, cancellation and
unexpected exceptions. Disposal includes transaction rollback where needed,
connection invalidation, `engine.dispose()`, secret callback exit and deletion of
references held by the composition.

The pool should use the smallest practical size, normally one connection and no
overflow. Verification must have bounded connection, statement and lock timeouts.
Cancellation is failure; it cannot preserve a prior `VALID` decision.

## Startup, release and offline operation

The same composition may be invoked in three modes:

- **release verification:** an isolated CI/CD job before promotion;
- **startup verification:** a pre-start init job or supervisor step before API
  workers are created;
- **recovery verification:** an isolated disaster-recovery job after restore and
  before recovered services receive traffic.

The preferred production deployment is a pre-start/init job. If application
startup invokes it, invocation must occur before constructing the API dependency
container, and the verifier pool must be disposed before `create_app()` runs.
HTTP handlers never receive the verifier result object; readiness receives only a
signed or locally held binary gate outcome tied to release, database and timestamp.

## Preventing HTTP access

- Place composition in infrastructure/deployment code, outside `jmoraIs.api`
  service contracts and endpoint dependencies.
- Do not export it from API composition modules or dependency containers.
- Do not register routes, background tasks or callable application services for
  replay.
- Build the verifier before API workers and destroy it before app construction.
- Use a separate credential reference unavailable to the API runtime identity.
- Enforce network and IAM policy so API service accounts cannot resolve the
  verifier credential.
- Add architecture tests prohibiting verifier imports from API handlers,
  bounded-context domain/application packages and normal repositories.

Process separation plus credential separation is the primary control. Python
module privacy alone is not a security boundary.

## Audit model

Every attempt records an append-only metadata event containing:

- execution ID and correlation ID;
- mode: startup, release or recovery;
- actor/workload identity;
- release, build and source revision;
- database identity hash, not a connection URL;
- verifier role and credential reference/version;
- replay policy and engine version;
- start/end timestamps and duration;
- stream and event counts;
- overall `VALID`, `TAMPERED` or `FAILED` result;
- failed stream identifiers and normalized reason codes;
- resource-disposal outcome.

Audit must not contain event payloads, patient or tenant data, secrets, tokens or
raw database errors. Audit persistence cannot reuse the read-only verifier
connection. It uses an existing operational audit capability or an external
append-only security sink. Failure to persist the terminal audit event blocks
release/startup approval.

## Operational model

- Single verifier execution per database/release is enforced by deployment
  orchestration or a non-mutating external lease; the verifier must not acquire a
  database write lock.
- Replay runs against a coherent snapshot and has explicit performance budgets.
- Timeouts, database unavailability, replica lag uncertainty, schema mismatch and
  audit failure all fail closed.
- A primary or a demonstrably consistent restored database is required. A replica
  is eligible only when its recovery/LSN consistency is independently proven.
- Results expire at a configured operational interval and whenever deployment,
  migration, restore or integrity-sensitive incident changes the verified state.
- No successful result is cached across database identity, schema head, release or
  build changes.

## Risk analysis

### Privilege abuse — critical impact

`BYPASSRLS` provides cross-tenant visibility. Controls are process isolation,
read-only default transactions, explicit grants, separate short-lived credentials,
no API identity access, connection limits, network isolation and append-only
execution audit.

### Exfiltration through reports — high impact

Replay reports may reveal stream identifiers. External results must contain only
opaque identifiers and normalized reason codes. Detailed forensic output remains
inside an approved security environment.

### Incomplete snapshot — high impact

Independent queries outside a coherent snapshot can observe checkpoints and
events at different moments. Execute the entire replay in one repeatable-read,
read-only transaction or evolve the existing engine to accept a connection in a
separately reviewed increment. Until coherent-snapshot execution is proven, do not
classify the verifier as production-ready.

### Audit dependency failure — high impact

The verifier cannot write through its read-only connection. A separate durable
audit sink is required, and release/startup fails if the terminal event cannot be
recorded.

### Resource exhaustion — medium impact

Large histories can consume database I/O and verifier memory. Enforce one-connection
pools, time budgets, bounded report detail, operational scheduling and measured
replay budgets. Never weaken completeness to meet a performance target.

### Credential persistence — critical impact

An exported or long-lived verifier credential would turn an offline boundary into
a cross-tenant data-access capability. Dynamic credentials and immediate pool
disposal are required production controls.

## Alternatives considered

### Reuse the API runtime role

Rejected. RLS intentionally hides other tenants, causing incomplete replay and a
correct `TAMPERED` decision.

### Grant `BYPASSRLS` to the API runtime

Rejected. This destroys tenant isolation and violates least privilege.

### Iterate through tenants with the API role

Rejected. Tenant enumeration becomes a completeness oracle, checkpoint discovery
remains problematic and verification depends on mutable tenant configuration.

### Duplicate replay logic in a new service

Rejected. It creates a second integrity truth and increases divergence risk.

### Add verifier-specific RLS policies

Feasible but not recommended for RC1. It avoids `BYPASSRLS` while increasing every
tenant-table policy and migration obligation.

### Run only as a permanent sidecar

Rejected. A resident privileged process unnecessarily enlarges the attack surface.
An ephemeral job or pre-start process is preferred.

## Trade-offs

- A dedicated privileged role increases credential-governance burden but preserves
  strict API tenant isolation.
- `BYPASSRLS` yields reliable completeness with a small policy surface, at the cost
  of requiring strong operational isolation.
- A pre-start job adds deployment complexity but prevents privileged resources from
  coexisting with HTTP handlers.
- One coherent snapshot can increase transaction duration and vacuum pressure; it
  is necessary for deterministic checkpoint/event comparison and must be bounded by
  measured budgets.
- Failing startup on audit failure favors accountability over availability, matching
  the platform's priority order.

## Recommended architectural decision

Adopt an ephemeral, independently authenticated `OfflineReplayVerifier` composition
that orchestrates the existing `PostgreSQLCryptographicReplayEngine`. Do not create
a bounded context or duplicate replay port. Provision a dedicated, globally visible
but strictly read-only PostgreSQL verifier role and a separate short-lived KMS-backed
credential. Run it as a release, pre-start or recovery job, dispose all resources
before API construction and expose only a release-bound binary gate result.

Implementation authorization must explicitly include:

1. dedicated verifier credential purpose and KMS/IAM policy;
2. dedicated PostgreSQL role with approved global-read mechanism;
3. coherent-snapshot replay proof;
4. separate durable audit sink;
5. architecture tests preventing API reachability;
6. timeout, disposal, RLS separation and credential-revocation tests.

**READY FOR RC1 IMPLEMENTATION**

## Implemented composition

`jmoraIs.infrastructure.offline_replay` now implements the approved ephemeral
composition. Migration `050_offline_replay_verifier` provisions the dedicated
role, explicit replay-table grants and append-only metadata audit. Each execution
uses one read-only repeatable-read connection and disposes its pool before API
construction continues. Only the binary decision and safe counters survive.
