# Audit Defense AI — MIP-09

## Human-review governance projection

The Audit Defense owner exposes review constraints through `AuditDefenseReviewGovernanceAdapter`, using the persisted opaque package reference and exact query path. Only existing critical limitations and reviewer attribution are projected; no clinical reasoning or conflict adjudication occurs.

## Exact persisted Stage-12 handoff

Controlled Stage-13 composition uses the owner-issued `PersistedDefensePackageReference`. The repository issues it only for a persisted package containing the exact Stage-11 document reference. After restart, `get_exact(reference)` reconstructs and verifies that package without `latest()` or caller-provided identity scalars. See `AUDIT_DEFENSE_EXACT_PERSISTED_REFERENCE.md`.

## Boundary

`jmoraIs.audit_defense` accepts only a ready `ClinicalReasoningInput` and resolves governed clinical-state facts, active `GovernedEvidence`, MIP-06 guideline recommendations, MIP-07 orthopedic assessments and active version-matched terminology through ports. Raw Patient Context, EvidencePackage, scientific connectors, payer payloads, dictionaries and arbitrary audit text are rejected.

## Deterministic defense model

The output is an immutable, reference-only `DefensePackage`. Each `DefenseArgument` binds clinical, scientific and guideline support to explicit terminology, policy and provenance. Supporting, opposing, neutral and inconclusive evidence remain separate. Counterarguments are deterministic flags derived only from opposing evidence or guideline conflicts. Missing data, conflicts, stale inputs and upstream limitations remain visible; the service does not invent a diagnosis, procedure, indication, citation or narrative claim.

## Review, persistence and prohibited use

Critical conflicts and insufficient support produce `REVIEW_REQUIRED` and block approval. Review delegates to canonical reviewer governance. Approval never creates autonomous authorization or external actionability. Versions and audit events are append-only in memory and PostgreSQL, with predecessor linkage, restart reconstruction and database rejection of UPDATE/DELETE.

The module contains no payer-specific logic, LLM, RAG, embeddings, authorization decision, treatment selection, surgical indication or citation generation. Institutional audit policy, IAM, tenant isolation, reviewer operations and external legal/clinical validation remain prerequisites for deployment.

## Stage-11 workflow trace

Audit Defense remains independent from Medical Document content. A dedicated
reference-only traceability service may append a new `DefensePackage` version that
points to the exact persisted Stage-11 `MedicalDocumentVersion`. The service uses
the canonical document repository under RLS and stores no prose or document
payload. See `docs/STAGE11_STAGE12_TRACEABILITY.md`.

## Typed Stage-13 issuance

Only the final Stage-11-linked `DefensePackage` is eligible for governed Gateway
issuance. `AuditDefenseGatewayInputIssuer.issue_from_package()` accepts that typed
persisted handoff, performs an exact repository equality check, validates the
version/predecessor chain and resolves the linked document before deriving the
AuditDefense DTO and attestation. The scalar API is legacy compatibility and must
not be used by COMPLETE_CASE.
