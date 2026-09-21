# Governed Orthopedic State

`GovernedOrthopedicStateView` is the immutable, reference-oriented projection consumed by MIP-07. It preserves pseudonymous subject, Clinical State identity/version, terminology version, orthopedic references, epistemic status, quality conflicts, provenance, projection policy, timestamp and predecessor.

The platform uses deterministic restart-safe reconstruction instead of a duplicate projection table. `PostgreSQLGovernedOrthopedicStateQueryAdapter` reads persisted Clinical State under PostgreSQL RLS and delegates to `OrthopedicStateProjectionService`; terminology is resolved through the canonical PostgreSQL-backed terminology service. No cache or original Python object participates.

Projection version equals Clinical State version, predecessor linkage equals the prior state ID, and the source `as_of` is the deterministic generation timestamp. Ambiguous or unknown terminology fails closed. The projection does not diagnose, reinterpret imaging, infer treatment or silently resolve conflicts.

The view is tenant-scoped patient-derived data. Isolation is inherited from `patient_clinical_state_versions`. The runtime engine binds tenant context transaction-locally and RLS protects a query that deliberately has no tenant predicate. Wrong or missing tenant context yields no projection; runtime roles remain `NOBYPASSRLS`.

For stage 10, MIP-07 requests the persisted state reference through `GovernedOrthopedicStateQueryPort`, receives the reconstructed view and persists its assessment through the existing PostgreSQL repository. Direct view construction in E2E composition is prohibited.
