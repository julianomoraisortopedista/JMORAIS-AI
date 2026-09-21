# Deployment Security

Supply-chain promotion is governed by `docs/SOFTWARE_SUPPLY_CHAIN_SECURITY.md`. Deployment accepts only an independently verified release manifest with matching source, Alembic head, hash-locked dependencies, SBOM/SCA/SAST/secret-scan evidence, artifact digest, provenance and institutional signature. `INSTITUTIONAL_SIGNING_PENDING` is never production-eligible.

The production image uses a Python 3.12 multi-stage build, pinned runtime dependency lock, non-root UID/GID 10001, loopback binding, bounded concurrency, bounded keepalive and graceful shutdown. Build context excludes tests, local environments, credentials and key material. No secret is accepted as a build argument or baked environment value.

Run the container without privileged mode or host networking, drop all Linux capabilities, enable `no-new-privileges`, mount the root filesystem read-only and provide only `/tmp/jmorais` as a bounded `tmpfs`. External secret/KMS and IAM adapters are injected by the deployment composition factory. Never mount source trees, Docker sockets or credential directories.

Global replay uses a distinct purpose-scoped KMS credential unavailable to the
API service identity. It runs before traffic through an ephemeral one-connection
pool and a dedicated read-only PostgreSQL role with controlled `BYPASSRLS`. Never
grant this role or credential to API workers, handlers or background tasks.

TLS terminates only at an approved internal reverse proxy. The proxy must replace—not append—forwarded headers, restrict source networks and pass them only from configured trusted CIDRs. The application must not be published directly and must not trust arbitrary `X-Forwarded-*` values. Liveness is process-only; authenticated readiness determines traffic eligibility.

The application independently enforces configured trusted proxy CIDRs, TLS scheme, host allowlist, actual request-body bounds, admission rate, concurrency and timeout. See `RUNTIME_SECURITY.md` and `NETWORK_SECURITY.md`. Certificates, firewall rules and distributed ingress limiting remain institutional controls and are not stored here.

JSON logs are metadata-only and redact credential, token, patient-context and evidence-package markers. Clients never receive stack traces. Tenant identifiers may be emitted only under institutional logging policy. Metrics and audit exporters must be durable production-safe adapters.

Prohibited patterns include public ingress, root execution, privileged containers, host networking, mutable image filesystems, environment-secret baking, migration-owner runtime access, `BYPASSRLS`, in-memory security state, disabled session validation, unbounded workers/timeouts and automatic fallback to development composition.

This is production-engineering hardening only. Real cloud deployment, institutional IAM/KMS onboarding, network policy, backup/restore operations, incident response and clinical authorization remain separate release gates.
