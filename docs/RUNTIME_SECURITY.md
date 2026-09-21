# Runtime Security

## Production admission boundary

Production binds the application to loopback and requires an approved ingress proxy. `RuntimeSecurityMiddleware` rejects plaintext requests, untrusted `Host` values, forwarding headers from sources outside the configured CIDRs, bodies larger than the configured byte limit and requests exceeding bounded admission rates. It reads and bounds the actual ASGI body, so a missing or forged `Content-Length` is not a bypass. Security responses contain only a stable code and correlation reference.

The runtime enforces bounded concurrency and request timeout. Uvicorn independently bounds workers, concurrency, keep-alive and graceful shutdown. The local limiter is defense in depth and keys on a one-way digest of the presented credential plus endpoint; the institutional ingress must enforce the same tenant/principal/endpoint policy across all replicas. Raw credentials are never retained as limiter keys.

## Transport and HTTP controls

- TLS is mandatory outside explicit development/test profiles. The sole production plaintext exception is process liveness from a loopback peer; it exposes no dependency state. Redirects are not a security control.
- Forwarding metadata is accepted only from configured proxy CIDRs; wildcard trust is invalid.
- Allowed hosts are explicit and cannot include `*`.
- Production CORS is absent because this is an internal service API, not a browser API.
- Responses use `no-store`, `nosniff`, frame denial and `no-referrer`. HSTS belongs at the approved TLS ingress, which sees the external secure channel.
- Liveness is dependency-free. Authenticated readiness represents whether serving is safe.

## Dependency failure policy

Database, IAM/JWKS, KMS/secrets, reviewer authorization and mandatory governance failures block startup or readiness. Provider/scientific failures block only the affected workflow. Authorization, validation, integrity failure, revoked credentials and `TAMPERED` replay are never retried. Idempotent external reads may use bounded, jittered retries only inside their owner adapter. The current connectors use explicit timeouts; institutional provider transports must additionally declare connection/read and retry budgets before enablement.

Circuit breakers are not applied to PostgreSQL, authorization or replay because fail-closed bounded failure is safer. They may be introduced behind scientific/LLM provider ports only after measured failure behavior and an operational reset policy exist.

## PostgreSQL

The API pool has explicit size, overflow, acquisition/connect timeout, statement timeout, lock timeout, idle-transaction timeout and `application_name`. Production requires database TLS. RLS is transaction-bound and the runtime role remains `NOBYPASSRLS`. Offline replay uses a distinct single-connection pool, read-only transaction, dedicated credential/role and immediate disposal.

## Failure classification

| Failure | Behavior |
|---|---|
| Database, OIDC/JWKS, KMS or reviewer governance unavailable at startup | Startup blocked |
| Required readiness dependency later unavailable | Traffic removed; liveness remains live |
| Replay `TAMPERED` | Startup/release/recovery blocked |
| Invalid release provenance/signature | Promotion blocked |
| External scientific/LLM timeout | Affected request blocked, safely classified; no autonomous fallback |
| Telemetry unavailable | Processing remains bounded; readiness/alerting policy determines traffic eligibility |
