# Performance Engineering — RC2

RC2 measures software behavior without changing clinical, scientific, governance, RLS, exact-reference, append-only, replay, or Human Review semantics. Synthetic data and `MockProviderAdapter` are mandatory. Reports in `evaluation/performance/` are local evidence, not production commitments.

## Environment and baseline

The measured host used Python 3.12.13, PostgreSQL 16.14, macOS arm64, 8 logical CPUs and 8 GiB RAM. The database was at Alembic `050_offline_replay_verifier`, approximately 13.2 MB before scale loading, with one tenant. The in-process API benchmark used 300 requests per rung at concurrency 1/2/4/8/16/32. Production defaults remained two ASGI workers, concurrency limit 100, application pools 10+5 and isolated verifier pool 1+0.

Authenticated `/version` traffic completed with 100% success. At concurrency 1, p50/p95/p99 were 0.514/0.586/0.654 ms and throughput was 1,868 requests/s. At 8 they were 2.79/3.25/3.64 ms and 2,682 requests/s. At 16 they were 5.30/19.79/21.03 ms and 2,493 requests/s. At 32 they were 9.10/10.85/12.86 ms and 3,173 requests/s. These in-process figures exclude network, proxy and external IAM latency.

PostgreSQL `SELECT 1` p50/p95/p99 was 1.04/1.15/2.14 ms, approximately 964 transactions/s. SHA-256 plus HMAC p50/p95/p99 was 0.00217/0.00242/0.00246 ms, approximately 488,093 operations/s. Provider latency was excluded.

Workloads B–S in `rc2-scenarios.json` are three-sample pytest wall times including interpreter startup and fixtures. They are regression evidence, not endpoint latency. COMPLETE_CASE p50 was approximately 2.05 seconds and replay p50 approximately 1.12 seconds in that scope.

## PostgreSQL, replay, and memory

EXPLAIN JSON for exact MedicalDocumentVersion, DefensePackage, LLMInvocation and ClinicalReasoningInput reads used existing primary/unique index scans. No index was added: no measured plan justified its write and storage cost. Advisory locking, deterministic ordering, retry-on-conflict and bounded pool/statement/lock/idle-transaction timeouts remain unchanged.

Final full replay at 100, 10,000 and 100,000 newly appended events measured 0.017, 0.191 and 2.326 seconds, all `VALID`; the accumulated LARGE run verified 110,100 events. Single-stream throughput was approximately 16,620, 38,303 and 36,845 events/s; append throughput was 6,823, 6,899 and 1,568 events/s. Process high-water RSS was 64 MB, 118 MB and 581 MB. The large result sizes the isolated verifier, not API workers.

Five sustained API cycles retained 82,099 bytes after GC while traced memory approached a plateau; no reproducible leak was observed. This does not replace a long soak.

## Bottleneck and minimal correction

Package reread previously replayed every global ledger row. Combining COMPLETE_CASE with 110,100 synthetic events amplified one exact package read into a global reconstruction. The repository now scopes the projection to the package's signed `claim_ids`; PostgreSQL remains canonical, integrity verification remains mandatory, and no cache, `latest()`, or trust bypass was introduced. A regression test proves unrelated claims cannot enter the projection.

Post-change validation passed: COMPLETE_CASE 1→14 completed in 2.57 seconds on the clean database and in 12.90 seconds against the representative 100,000-event dataset. Replay remained `VALID`; the former unbounded package-read amplification was not reproduced.

## Regression budgets and limits

Budgets are deliberately generous: API p95 250 ms, database p95 50 ms, 100% success, retained growth under 8 MiB, medium replay under 15 seconds, large replay under 30 seconds, and replay `VALID`. They detect order-of-magnitude regressions without claiming institutional SLOs.

No live LLM, network proxy, external OIDC/KMS, multi-host database, institutional dataset, 64/128 rung, multi-worker deployment, or long soak was measured. Queue time is not separately instrumented. Production capacity requires target-environment evidence.
