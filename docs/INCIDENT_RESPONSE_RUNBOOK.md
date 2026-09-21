# Incident Response Runbook

## Authority and safety

The institutional incident commander, security owner, database owner, clinical-governance owner and privacy/legal authority must be named before deployment. These owners are currently unresolved institutional prerequisites. Automated destructive remediation is prohibited.

## Procedure

1. **Detection:** correlate immutable audit, release identity, replay decision and metadata-only telemetry. Treat replay tamper, RLS failure, credential compromise and provenance failure as critical.
2. **Triage:** assign severity; record UTC time, release/build, correlation IDs, affected tenant scopes and evidence locations without copying clinical payload.
3. **Containment:** freeze deployment and remove affected workloads from readiness. Restrict network access. Do not alter ledgers or delete suspected records.
4. **Evidence preservation:** snapshot logs/audits, release manifest, SBOM/provenance, database backup and key/version metadata into institutionally controlled immutable storage. Maintain custody, hashes and authorized access.
5. **Credentials and keys:** use the institutional IAM/KMS authority to revoke affected service credentials, sessions/JTIs or key versions. Never rotate by editing repository configuration. Record every revocation.
6. **Database verification:** restore a protected copy, verify Alembic/RLS/roles, execute OfflineReplayVerifier, and classify exclusively `VALID` or `TAMPERED`.
7. **Recovery:** deploy only a signed, verified release; restore through authorized credentials; replay and compare deterministic state before traffic. Never repair an integrity chain silently.
8. **Post-incident review:** document root cause, affected scope, residual clinical/privacy/regulatory risk, controls, owners and dated follow-up.

## Event categories

Credential compromise, replay tamper, session replay, cross-tenant attempt, release signing/provenance failure, KMS/key revocation, dependency compromise and data-integrity alert are canonical operational incident categories. Events contain attribution and references, never the underlying clinical narrative or secrets.

## Backup/DR security

Backups require encryption with independently managed keys, separate least-privilege credentials, immutable/offline copies, authorized retention and restore approval. Restore targets are isolated; the process verifies Alembic compatibility, roles/RLS, append-only controls, replay and deterministic state equivalence. The existing deterministic restore/replay suite is engineering evidence only; no institutional backup platform is claimed operational.
