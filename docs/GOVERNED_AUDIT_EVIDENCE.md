# Governed Audit Evidence

Audit Defense resolves scientific support through `CanonicalGovernedAuditEvidenceAdapter`, an implementation of the existing `GovernedAuditEvidencePort`. The adapter composes the canonical persisted `GovernedEvidence` query, Clinical Appraisal query and current lifecycle service. It creates no evidence DTO, repository, score or truth store.

The returned value remains the immutable canonical `GovernedEvidence`. It preserves the opaque GovernedEvidence and EvidencePackage IDs, appraisal linkage, evidence hierarchy, methodological quality, recommendation strength, applicability, guideline governance, canonical support directions, provenance, ledger references, policy/appraisal versions, limitations, issuance timestamp and integrity hash. Scientific payloads and raw EvidencePackage objects never enter Audit Defense.

`SUPPORTING`, `OPPOSING`, `NEUTRAL` and `INCONCLUSIVE` are retained from the canonical scientific `SupportDirection`; the adapter does not collapse or reinterpret them.

Every query revalidates GovernedEvidence integrity and its current EvidencePackage through `GovernedEvidenceService`, validates the persisted appraisal record and integrity linkage, and asks `GovernedEvidenceReevaluationService` for current lifecycle. Missing, forged, integrity-invalid, appraisal-incomplete, package-revoked, superseded, invalidated or otherwise non-`ACTIVE` evidence fails closed.

GovernedEvidence follows its existing tenant-scoped classification under `governed_evidence_versions` and `governed_evidence_lifecycle_events`. PostgreSQL runtime roles and RLS protect the persisted query; no patient or clinical payload is added to the evidence projection. EvidencePackage and scientific ledger ancestry remain shared scientific truth behind their existing boundary.

Restart safety is provided by recomposing the canonical PostgreSQL repositories and services. There is no cache or process-local evidence state. This adapter closes only the Stage-12 evidence prerequisite; guideline, orthopedic and terminology ports remain independent gates.
