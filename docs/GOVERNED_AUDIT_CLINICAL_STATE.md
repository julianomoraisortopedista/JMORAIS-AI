# Governed Audit Clinical State

This projection supplies immutable `GovernedAuditClinicalFact` references to Audit Defense from the canonical persisted `PatientClinicalState`. It introduces no diagnosis, treatment, indication, causal statement, medical-necessity assessment or payer conclusion.

The implementation uses deterministic restart-safe reconstruction rather than a second clinical truth store. `PostgreSQLGovernedAuditClinicalStateAdapter` reads the existing RLS-protected Clinical State JSONB by opaque state ID and delegates to `AuditClinicalStateProjectionService`. No projection table, cache or process-local handoff exists.

Projected categories are limited to facts already represented by Clinical State: problems, symptoms, findings, medications, allergies, procedures, implants, pain, risks, laboratory and imaging references, functional limitations, orthopedic references and data-quality references. Each fact retains the pseudonymous subject reference, Clinical State ID/version, original fact/source reference, epistemic status, terminology references when already governed, timestamp, provenance, policy version, review status and quality flags. The projection never copies the complete Clinical State aggregate.

Epistemic values remain `CONFIRMED`, `REPORTED`, `OBSERVED`, `SUSPECTED`, `INFERRED` or `UNKNOWN`. Missing, conflicting, stale, unverified, timeline, unit, laterality and duplicate-event flags remain explicit. `REVIEW_REQUIRED` is preserved without promotion or silent normalization.

Because the projection is patient-derived, it is tenant-scoped. Isolation is inherited from `patient_clinical_state_versions`: transaction-local `TenantContext` and PostgreSQL RLS enforce same-tenant reads and fail closed for cross-tenant or missing-context reads. The adapter intentionally contains no tenant predicate, so authorization remains enforced by PostgreSQL runtime roles with `NOBYPASSRLS`.

The Stage-12 handoff is `persisted PatientClinicalState → GovernedAuditClinicalFact → GovernedAuditClinicalStatePort → AuditDefenseService`. This closes only the Clinical State prerequisite; all other Stage-12 governed inputs remain independently required.
