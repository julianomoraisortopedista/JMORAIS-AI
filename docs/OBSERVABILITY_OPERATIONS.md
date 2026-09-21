# Observability Operations

Observability is metadata-only. Logs, metrics and traces must never contain direct identity, patient context, clinical narrative, prompts, model responses, JWT/JTI, DSNs, credentials, key material or secret values.

`BoundedOpenTelemetryExporter` requires an HTTPS collector endpoint on an explicit host allowlist, bounded buffer and exporter timeout. Buffer overflow drops telemetry deterministically and increments a local drop count; it never blocks clinical/governance processing indefinitely. Collector credentials must be resolved through the Secrets boundary. External collector and alert delivery were not available during local validation and are not claimed operational.

Approved low-cardinality dimensions are route template, method, status class, outcome, component and policy/build version. Tenant/principal values, when institutionally approved, must be opaque and cardinality-controlled.

Required metric families include authentication failures, authorization denials, session replay, RLS failures, secret/KMS failures, provider failures, replay decisions, Human Review security events, rate limiting, latency, DB saturation, external timeout and readiness/startup failures.

## Alert policy

| Severity | Condition | Required action |
|---|---|---|
| CRITICAL | replay `TAMPERED`, RLS failure, release signature/provenance failure, unexpected privileged DB role | freeze promotion/traffic, preserve evidence, invoke incident authority |
| CRITICAL | sustained inability to resolve mandatory secrets/keys | remove readiness and investigate compromise/availability |
| HIGH | abnormal session replay or cross-tenant attempts | security triage and identity/session containment |
| HIGH | sustained authorization failure, DB saturation, critical provider outage | rate-limit/isolate affected workflow and investigate |
| MEDIUM | elevated timeouts, telemetry drops, dependency degradation | operational review within institutional SLO |

Institutional SIEM/Alertmanager ownership, thresholds, paging destinations and retention remain prerequisites.
