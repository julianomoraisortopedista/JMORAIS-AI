# Clinical Reasoning Input — Exact Upstream Lineage

New canonical `ClinicalReasoningInput` versions preserve the owner-issued exact
references consumed during assembly: `PersistedClinicalStateReference`, the
complete tuple of `PersistedGovernedEvidenceReference`, and the complete tuple
of `PersistedTerminologyMappingGovernanceReference`.

The application service resolves every reference through its owner's
`get_exact` port before persistence. Scalars never establish trust. The
references are immutable metadata embedded in the versioned canonical document;
relational columns preserve their identifiers for consistency checks, without
duplicating clinical or scientific payloads.

Older records remain readable and immutable, but expose
`LEGACY_MISSING_PERSISTED_CLINICAL_REASONING_INPUT_REFERENCE` and are ineligible
for the S003 exact-lineage path. Missing or partial lineage fails closed.

The owner-issued `PersistedClinicalReasoningInputReference` binds the exact input
version and predecessor, tenant, policy, provenance, input hash and all typed
upstream references. `get_exact(reference)` revalidates canonical persistence and
each upstream owner contract. Its append-only PostgreSQL family is RLS-protected
and anchored in cryptographic completeness checkpoints.
