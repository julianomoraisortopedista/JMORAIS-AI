# Terminology Mapping Governance Persistence

## Architectural boundary

`ClinicalConcept` remains the canonical terminology truth: identity, codes, lifecycle,
version, source and provenance. Mapping-specific decisions are stored separately as
immutable `TerminologyMappingGovernanceRecord` versions. No concept lifecycle state is
used to infer mapping confidence, review state or policy after restart.

Canonical flow:

`source term/code → MappedClinicalConcept → TerminologyMappingGovernanceRecord → append-only persistence`

Restart reconstruction:

`persisted ClinicalConcept + persisted mapping-governance history → governed terminology projection`

No remapping, provider call, cache or process-local mapping result is required.

## Canonical governance record

Each version preserves its opaque ID, source reference and term, source code system,
selected concept, terminology version, mapping type, actual confidence, review status,
explicit review requirement, reviewer attribution when applicable, mapping method,
policy version, provenance, timestamp, version, predecessor and integrity hash.

`EXACT`, `EQUIVALENT`, `BROADER`, `NARROWER`, `RELATED` and `UNMAPPED` remain distinct.
`AUTO_MAPPED` does not become `REVIEWED` after restart. Policy changes create new
versions and never rewrite historical decisions.

## Persistence and tenancy

The PostgreSQL stream is append-only. A unique stream/version constraint and predecessor
validation preserve ordering; database triggers reject `UPDATE` and `DELETE`. Integrity
is recomputed on append and governed projection.

This implementation is explicitly **shared global reference data** because its records
represent generic terminology mappings and contain no patient, case, organization or
tenant payload. Tenant-derived free-text mappings remain out of scope and require a
separately classified tenant-scoped design.

## Audit Defense projection

`PostgreSQLGovernedAuditTerminologyAdapter` implements the existing
`GovernedAuditTerminologyPort`. It reconstructs and validates both canonical histories,
then releases a `ClinicalConcept` to the unchanged Audit Defense service only when the
concept is active and the mapping is eligible. Missing, corrupt, mismatched, rejected,
review-required, low-confidence or policy-incompatible records fail closed.

This closes the Stage-12 restart gap without duplicating terminology truth or changing
Audit Defense business semantics.
