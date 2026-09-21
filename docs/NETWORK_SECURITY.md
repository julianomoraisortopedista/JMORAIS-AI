# Network Security

Default deny is the production policy. Actual firewall, service-mesh and DNS enforcement are institutional deployment prerequisites.

| Source | Destination | Port/protocol | Direction and necessity | Failure behavior |
|---|---|---|---|---|
| Internal client | Approved ingress | 443/TLS | inbound API access | reject plaintext/untrusted host |
| Ingress trusted CIDRs | API loopback/private listener | configured HTTP/private transport | only ingress reaches API | reject other sources and spoofed proxy headers |
| API runtime | PostgreSQL | 5432/TLS | governed reads/audit writes | fail readiness/affected request |
| API runtime | Secrets/KMS | 443/TLS | credentials and key operations | fail closed; no cached unsafe fallback |
| API runtime | OIDC/JWKS allowlist | 443/TLS | identity verification | authentication unavailable |
| Scientific connector workload | NCBI/Crossref-approved hosts | 443/TLS | authoritative retrieval | bounded unavailable result |
| LLM Gateway workload | approved provider endpoint | 443/TLS | governed provider invocation | workflow blocked/review-required |
| API/runtime | approved OTel collector | 4317 or 4318/TLS | metadata-only telemetry | bounded drop/failure; never payload fallback |
| Offline verifier job | PostgreSQL | 5432/TLS | ephemeral global read-only replay | job fails, pool disposed |
| Offline verifier job | Secrets/KMS | 443/TLS | ephemeral verifier credential | verification blocked |

The API cannot select arbitrary provider URLs. OIDC issuer/JWKS, telemetry collector, scientific providers and LLM providers must be drawn from deployment allowlists. Redirects to an unapproved host are prohibited at transport adapters. The verifier is unavailable to HTTP routing and uses independent credentials and network policy. No unrestricted Internet egress is approved.
