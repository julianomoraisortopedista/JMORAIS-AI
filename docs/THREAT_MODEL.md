# Threat Model — RC1 Runtime

Method: STRIDE over production trust boundaries.

| Boundary/asset | Threat and attacker path | Control | Residual risk |
|---|---|---|---|
| HTTP ingress | spoofed proxy/TLS/Host, DoS | loopback binding, trusted CIDRs, TLS/Host checks, body/rate/concurrency/time bounds | distributed enforcement and certificates institutional |
| IAM/OIDC | forged/replayed JWT, poisoned JWKS | asymmetric allowlist, issuer/audience/time checks, governed sessions/JTI, bounded HTTPS JWKS | IdP availability and credentialing institutional |
| Tenant/RLS | cross-tenant read/write | trusted tenant resolution, transaction-local context, PostgreSQL RLS, NOBYPASSRLS | privileged DBA remains trusted operator |
| PostgreSQL | injection, lock/resource exhaustion, mutation | parameterized SQL, pool/timeouts, roles, RLS, append-only triggers | HA/capacity and TLS infrastructure institutional |
| Secrets/KMS | disclosure, revoked key reuse | opaque references, managed boundary, readiness, audit, no repository keys | external KMS/HSM pending |
| Offline replay | HTTP privilege escalation, incomplete/tampered replay | isolated composition/credential/pool, read-only global role, immediate disposal | privileged infrastructure compromise |
| Scientific connectors | SSRF, malformed/untrusted metadata | fixed authoritative endpoints, timeouts, validation/reconciliation | provider availability and DNS/network controls |
| LLM Gateway | prompt/response leakage, provider misuse | DTO allowlist, prompt governance, Secrets boundary, metadata-only audit, Human Review | provider contract/ZDR and regional routing pending |
| Human Review | unauthorized/self approval | IAM/session, reviewer governance, tenant/policy constraints, immutable events | institutional reviewer credentialing |
| CI/supply chain | dependency/artifact substitution | hashed locks, SBOM/SCA/SAST, provenance, manifest verification | institutional signing pending |
| Observability | sensitive payload leakage, collector exfiltration | redaction, attribute denylist, HTTPS host allowlist, bounded exporter | collector/SIEM deployment pending |
| Operator/admin | excessive privilege or evidence deletion | separate roles, append-only, offline verification, auditable procedures | external anchoring and institutional segregation of duties |

No control here authorizes production healthcare use. LGPD/DPIA, clinical safety and regulatory decisions remain outside this engineering gate.
