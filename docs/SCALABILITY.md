# Scalability — RC2

JMORAIS-AI scales horizontally only while every worker preserves IAM, TenantContext, RLS, exact-reference and audit boundaries. PostgreSQL is canonical; global replay is an offline privileged operation and never shares the HTTP role or pool.

- API workers are bounded by CPU, memory and aggregate database connections.
- Exact queries and transaction duration must be measured before adding indexes or connections.
- Advisory locks serialize one canonical stream; independent streams can progress concurrently. Conflict remains fail-closed and retryable.
- Replay scaled from 0.017 to 0.191 to 2.326 seconds as the accumulated dataset reached 100/10,100/110,100 events. Its memory growth requires isolated verifier resources.
- Tenant-scoped mutable clinical state must not use unsafe shared caches.

The ladder stopped at 32 because higher in-process concurrency would not add credible deployment evidence on the 8-core/8-GiB host. The runtime bounds active work, request size, rate, database acquisition, statements and locks. PostgreSQL, OIDC, KMS and audit failures remain fail-closed.

Tenant A/B/C load must use real runtime roles and intentionally omit repository tenant predicates to prove database RLS. Transaction-local context must clear on pool reuse. This remains a mandatory release condition; throughput never overrides isolation.

Before scale-out, measure multi-worker latency, aggregate connections, pool/lock waits, deadlocks, CPU throttling, RSS p99, telemetry queue depth, backup/restore, replay RSS, external IAM/KMS, and COMPLETE_CASE p95/p99. Revalidate RLS, Session/JTI, audit, append-only, exact references and Human Review under that load.

Institutional hardware, cloud topology, HA/replication, provider SLA, regulatory targets and production SLO approval remain external prerequisites.
