# Governed Audit Guideline

Audit Defense resolves guideline support through `PostgreSQLGovernedAuditGuidelineAdapter`, an implementation of the existing `GovernedAuditGuidelinePort`. It returns the immutable canonical `GuidelineRecommendationSet`; no parallel guideline DTO, interpretation engine, repository or truth store is introduced.

The adapter composes the tenant-scoped `PostgreSQLRecommendationRepository`, persisted Clinical Reasoning Input, shared governed guideline-source history, Clinical Appraisal records and canonical terminology. It preserves recommendation-set identity/version, guideline ID/version, organization, intent, canonical recommendation strength, applicability, conflicts, review status, appraisal and terminology linkage, provenance, policies, limitations and timestamps.

Temporal validity reuses the same canonical MIP-06 rule used during recommendation generation. Withdrawn, expired, superseded, unappraised, terminology-mismatched and policy-mismatched sources fail closed. Appraisal integrity and eligibility, source version, recommendation history and deterministic set identity are revalidated after restart. Rejected upstream sets are ineligible; critical conflicts remain intact for Audit Defense limitations and counterarguments.

`RecommendationStrength`, `RecommendationIntent`, `ConflictSeverity` and reviewer status remain their canonical domain values. Reviewer approval is preserved but never converted into external actionability by this projection.

Guideline-source and terminology records retain their existing shared/global classification. Case-derived `GuidelineRecommendationSet` and Clinical Reasoning Input remain tenant-scoped. PostgreSQL runtime roles and RLS enforce same-tenant reads and fail closed for cross-tenant or missing-context access; the adapter contains no tenant filter or cache.

Restart safety is achieved by recomposing canonical PostgreSQL repositories and rereading all references. This closes only the guideline dependency of Stage 12; orthopedic and terminology Audit Defense ports remain independent gates.
