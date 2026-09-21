# Governed Document Clinical State

This projection supplies `DocumentFactReference` values to the Medical Document Engine from canonical persisted `PatientClinicalState`. It exposes only existing facts and source references; it does not create narrative, diagnosis, treatment, causality or procedure indications.

The architecture uses deterministic restart-safe reconstruction rather than duplicating clinical state. `PostgreSQLGovernedDocumentClinicalStateAdapter` reads the RLS-protected state by opaque ID and delegates to `DocumentClinicalStateProjectionService`. There is no cache or process-local handoff.

Problems, symptoms, findings, medications, allergies, procedures, implants, laboratory, imaging, function, pain, risk and orthopedic references retain the source Clinical State ID/version, original source reference, timestamp, provenance, terminology reference when already available, review status, policy and all data-quality flags. `SUSPECTED`, `INFERRED`, `REPORTED`, `OBSERVED`, `CONFIRMED` and `UNKNOWN` remain distinct.

Document facts are tenant-scoped patient-derived data. Isolation is inherited from `patient_clinical_state_versions`; transaction-local TenantContext and PostgreSQL RLS prevent cross-tenant and context-free reads even though the adapter query contains no tenant predicate. Runtime roles remain `NOBYPASSRLS`.

This closes only the Clinical State input of Stage 11. Persistent document terminology and canonical citation query adapters remain separate gates.

The terminology gate is now implemented by `PostgreSQLGovernedDocumentTerminologyAdapter`, a read-only projection over the canonical shared terminology repository. It creates no derived persistence. Active concepts map with high confidence; deprecated, retired, superseded and unknown concepts remain explicit and require review. Canonical citation resolution remains the next Stage 11 blocker.
