# Clinical Reasoning Input — MIP-04

> S003 hardening: novas versões canônicas preservam referências exatas tipadas de
> Clinical State, Governed Evidence e Terminology Governance. Consulte
> `CLINICAL_REASONING_INPUT_EXACT_LINEAGE.md`.

`jmoraIs.reasoning_input` is the sole governed input contract for future intelligent clinical modules. It contains traceable identifiers and version references only; it never embeds Patient Context, Patient Clinical State payloads, EvidencePackage content, scientific records, timeline events, laboratory values or images.

The contract binds a Patient Clinical State reference to context/state/terminology versions, governed-evidence and EvidencePackage references, applicable guideline references, timeline, quality summary, provenance, audits and policy versions. Readiness is deterministic and fail-closed. Automatically assembled, incomplete, conflicting, rejected or review-required inputs cannot be treated as ready.

Input versions and workflow events are append-only. Review, approval and rejection produce new immutable versions. This bounded context validates contract completeness and governance only; it performs no diagnosis, inference, prediction, recommendation or treatment selection.

External clinical use remains prohibited pending the identity vault, KMS/HSM, IAM/SSO, tenant isolation/RLS, human privacy adjudication, institutional terminology governance and definitive LGPD validation.

For controlled-pilot lineage, the contract also preserves an ordered tuple of owner-issued exact terminology-governance references. The existing `terminology_version` remains a release marker; it cannot reconstruct mapping ancestry. Legacy inputs without exact references remain queryable but are excluded from COMPLETE_CASE evidence.
