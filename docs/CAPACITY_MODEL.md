# Capacity Model — RC2

This model converts RC2 measurements into formulas. It is not an institutional capacity promise.

The local API remained error-free through 32 concurrent requests. Use 16 concurrent active requests per worker as a provisional engineering envelope until proxy, IAM, KMS, PostgreSQL and telemetry are measured together. Do not raise configured limits from this evidence alone.

`total_database_connections = workers × (pool_size + max_overflow) + verifier_connections + migration_and_admin_reserve`

Keep this below PostgreSQL `max_connections` after a deliberate safety reserve. Current defaults imply at most 15 application connections per worker and one isolated verifier connection.

`estimated_serial_cases_per_hour = 3,600 / measured_complete_case_seconds`

The local pytest-scoped p50 near 2.05 seconds implies roughly 1,756 serial cases/hour, but includes test overhead and excludes real external services. Institutional estimation must use:

`cases_per_hour = workers × effective_concurrency × 3,600 / production_case_p95 × measured_efficiency_factor`

The final API benchmark process high-water RSS was about 100 MB. Size workers from deployment soak p99. Size the offline verifier separately: the accumulated 110,100-event replay reached about 581 MB RSS. Local crypto cost was small relative to database/reconstruction work; choose workers only after CPU quota, memory and aggregate connections are known.

Admission is bounded by concurrency semaphore, fixed-window rate limit and database pool timeout. New work may return 429 for rate limits and 503 for unavailable mandatory dependencies. Atomic audit, append-only writes and Human Review must finish or roll back and cannot be partially shed.

## Proposed controlled-pilot SLO candidates

- PROPOSED authenticated lightweight API p95: 250 ms, excluding external IAM/network.
- PROPOSED eligible-request availability: 99.5%, excluding policy-driven 4xx.
- PROPOSED monthly error budget: 0.5%.
- PROPOSED release replay gate: `VALID` and large profile below the 30-second regression ceiling on the reference runner.

These require institutional approval and are not clinical, regulatory, contractual, or production commitments.
