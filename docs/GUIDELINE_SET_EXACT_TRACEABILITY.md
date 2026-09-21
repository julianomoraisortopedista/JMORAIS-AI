# Guideline Recommendation Set Exact Traceability

## Canonical ownership and handoff

The Guideline Engine owns `PersistedGuidelineRecommendationSetReference`. After a set is appended, `reference_for(set)` compares it with canonical persistence, validates its predecessor chain and issues an opaque tenant-scoped reference containing exact set ID/version, subject, policy, payload-integrity hash and issuance time.

Stage 9 hands that typed reference to Stage 11. Medical Document resolves it only through `GuidelineRecommendationQueryPort.get_exact(reference)`. Resolution validates the persisted reference, current tenant, RLS-visible exact set, subject, policy, provenance, payload hash and version chain. The document stores the same reference; it never selects a version.

The set reference is aggregate-level ancestry. `guideline_recommendation_ids` remain statement-level traceability and cannot infer set identity.

## Persistence, restart and legacy policy

`guideline_recommendation_set_references` is append-only and RLS-protected. `medical_document_versions` stores reference ID, set ID and set version as integrity-check columns while the typed reference remains in the immutable payload. The repository compares both representations when reading.

Restart path: `MedicalDocumentVersion → PersistedGuidelineRecommendationSetReference → get_exact(reference) → exact GuidelineRecommendationSet`. No `latest()`, history scan, recommendation-ID inference, manifest scalar or retained object participates.

Existing rows remain immutable and readable. A document without the typed reference is `LEGACY_MISSING_GUIDELINE_SET_REFERENCE`; it is never upgraded by inference and is ineligible as COMPLETE_CASE evidence.
