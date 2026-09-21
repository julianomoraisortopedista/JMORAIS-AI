# Audit Defense Exact Persisted Reference

`PersistedDefensePackageReference` is the owner-issued, restart-safe handoff from Stage 12 to Stage 13. It binds an opaque reference ID to one persisted `DefensePackage` stream, exact version, package ID, tenant, policy, integrity hash and issuance timestamp.

Only `AuditDefenseRepository.reference_for()` may issue the reference. Issuance requires an exact persisted package with a Stage-11 document reference and a complete predecessor chain. The metadata-only reference record is append-only and protected by PostgreSQL RLS; it never duplicates the defense or Medical Document payload.

After restart, `AuditDefenseQueryPort.get_exact(reference)` validates the stored reference record, current tenant, exact package identity/version, policy, package integrity, predecessor continuity and Stage-11 linkage. It never calls `latest()` and never accepts free stream/version arguments.

```text
final linked DefensePackage
→ reference_for(package)
→ PersistedDefensePackageReference
→ runtime disposal
→ get_exact(reference)
→ exact DefensePackage
→ AuditDefenseGatewayInputIssuer.issue_from_package(package)
```

Fabricated, stale, altered, cross-tenant and pre-traceability references fail closed.
