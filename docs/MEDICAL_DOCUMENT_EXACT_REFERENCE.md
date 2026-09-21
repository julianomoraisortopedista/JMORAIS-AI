# Medical Document Exact Persisted Reference

`PersistedMedicalDocumentVersionReference` is the Medical Documents owner-issued,
metadata-only trust input for the S003 Medical Document Viewer.

`reference_for(version)` proves exact equality with canonical PostgreSQL persistence,
including stream/version/predecessor continuity, tenant, policy, validation/review
status, provenance, traceability and the typed guideline and orthopedic references.
`get_exact(reference)` rereads the reference and exact document version after restart
without `history()`, `latest()`, or caller-provided stream/version scalars.

The reference contains no document sections or content. Persistence is append-only,
tenant-scoped, RLS-protected and included in cryptographic replay completeness.
The existing `MedicalDocumentVersionReference` remains unchanged for the approved
Stage 11→12 compatibility path and is classified as non-S003 trust; no historical
reference is synthetically converted.
