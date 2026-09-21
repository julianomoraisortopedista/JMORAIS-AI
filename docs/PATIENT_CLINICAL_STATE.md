# Patient Clinical State — MIP-03

`jmoraIs.clinical_state` is a derived, immutable bounded context. It consumes only authorized, versioned Patient Context through `PatientContextQueryPort`; it never accepts identity data or raw ingestion payloads.

The state preserves source references, provenance, epistemic status and problem lifecycle. Assembly is deterministic and cannot promote reported, suspected or inferred information to confirmed. Confirmation and all other lifecycle changes require an explicit append-only transition with actor, source event, rationale and provenance.

Snapshots and audit events are append-only in memory and PostgreSQL. Conflicts are retained as data-quality flags and force `REVIEW_REQUIRED`. Review and correction create new versions. The module contains no diagnosis, differential ranking, treatment selection, surgical indication, recommendation, prediction, LLM, RAG or embeddings.

External use remains blocked pending the direct-identity vault, KMS/HSM, IAM/SSO, tenant isolation/RLS, human adjudication of privacy review cases, and definitive institutional/legal LGPD policy.
