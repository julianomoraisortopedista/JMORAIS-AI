# Audit Defense Review Governance

`AuditDefenseReviewGovernanceAdapter` is the owner-side implementation of the Human Review `UpstreamReviewGovernancePort` for `artifact_type="AuditDefense"`.

It converts the Stage-13 `UpstreamArtifactReference` into the persisted opaque `PersistedDefensePackageReference` through the Audit Defense query boundary, calls `get_exact(reference)`, and validates tenant, policy, integrity, predecessor continuity and exact Stage-11 linkage. It never calls `latest()`, selects history by caller-provided version, or copies document/defense payloads.

Only existing governance facts are projected. Limitations already classified `CRITICAL` become critical-conflict references. Canonical `DefensePackage.reviewer_id` becomes the upstream reviewer attribution used by the existing self-approval policy; absent attribution remains `None` and is never inferred from the caller.

`UpstreamReviewGovernanceRouter` retains the existing Medical Document adapter and dispatches Audit Defense to its owner adapter. `AuthorizedLLMHumanReviewService` remains generic and approved review states remain externally non-actionable.
