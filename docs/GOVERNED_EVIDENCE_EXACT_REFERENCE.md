# Governed Evidence Exact Persisted Reference

`PersistedGovernedEvidenceReference` is the Governed Evidence owner-issued,
metadata-only trust input for the future S003 Evidence Viewer. Compatibility reads
by `governed_evidence_id` remain available internally but cannot establish workspace
trust.

`reference_for()` proves exact equality with the canonical PostgreSQL stream row,
its real `stream_version`, current valid EvidencePackage, eligible persisted
ClinicalAppraisal, policy, provenance and the latest hash-valid lifecycle event.
Only `ACTIVE` lifecycle is eligible. `get_exact()` repeats those checks after every
restart and rejects a newer invalidated, superseded or review-required lifecycle.

The reference stores no scientific, appraisal or clinical payload. Its table is
tenant-scoped, RLS-protected and append-only. Each insertion atomically creates an
independent completeness checkpoint; Offline Replay recomputes reference integrity
and compares row and checkpoint. Historical scalar-only rows are classified as
`LEGACY_MISSING_PERSISTED_GOVERNED_EVIDENCE_REFERENCE` for S003 purposes and are
never silently upgraded.
