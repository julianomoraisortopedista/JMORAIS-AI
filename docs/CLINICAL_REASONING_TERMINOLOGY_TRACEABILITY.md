# Clinical Reasoning Terminology Traceability

## Exact ancestry

Terminology owns `PersistedTerminologyMappingGovernanceReference`. The reference is issued only after a canonical `TerminologyMappingGovernanceRecord` is persisted and its identity, integrity, provenance and predecessor chain are verified. Terminology governance remains shared global reference data; this change does not add tenant semantics to it.

`ClinicalReasoningInput.terminology_governance_references` is an immutable, unique tuple ordered by opaque reference ID. Multiple references are required because one reasoning input may depend on multiple mapped concepts. `terminology_version` remains the aggregate release marker and does not replace exact ancestry.

Stage 8 receives references issued at Stage 4, resolves every reference through `TerminologyMappingGovernanceQueryPort.get_exact()`, rejects mismatched versions and ineligible mapping states, and persists the unchanged references. It never searches by version, remaps terms, selects latest history or interprets generic provenance as identity.

## Persistence and restart

The global append-only reference table stores no terminology payload. The tenant-scoped reasoning-input row stores only ordered opaque reference IDs as consistency metadata while the complete typed references remain covered by immutable canonical serialization. After restart:

`ClinicalReasoningInput → exact reference(s) → get_exact() → exact TerminologyMappingGovernanceRecord(s) → canonical concept ID(s)`.

Rows without references remain readable and are classified `LEGACY_MISSING_EXACT_TERMINOLOGY_GOVERNANCE_REFERENCE`. No history search or synthetic backfill upgrades them, and they are ineligible for COMPLETE_CASE evidence.
