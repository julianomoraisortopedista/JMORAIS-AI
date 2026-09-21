# Clinical Path Deprecation Policy

## Trusted path

The only trusted clinical path is:

`Scientific Core → EvidencePackage → Clinical Appraisal → GovernedEvidence → Lifecycle-aware Eligibility Gate → Clinical Intelligence → Authorized Human Review`

## Classification

| Path | Classification | Enforcement | Removal |
|---|---|---|---|
| `jmoraIs.clinical.ClinicalIntelligenceService` | KEEP | Public alias of `GovernedClinicalIntelligenceService`; requires GovernedEvidence and lifecycle gate. | No. |
| `GovernedClinicalIntelligenceService` | KEEP | Accepts opaque GovernedEvidence IDs only. | No. |
| `AuthorizedRecommendationReviewService` | KEEP | Requires `ReviewerAuthorizationPort`, identity, role, justification and policy. | No. |
| `ClinicalAppraisalService` → `GovernedEvidenceService` | KEEP | Mandatory appraisal/governance boundary. | No. |
| `jmoraIs.clinical.application.ClinicalIntelligenceService` | DEPRECATE | Constructor fails closed with `DeprecatedClinicalPathError`. | REMOVE_LATER after downstream migration confirmation. |
| `jmoraIs.clinical_engine.ClinicalDecisionEngine` | DEPRECATE | Constructor fails closed with `DeprecatedClinicalPathError`. | REMOVE_LATER after import telemetry/audit. |
| `RecommendationReviewService` | DEPRECATE | Constructor fails closed; absent from the public package contract. | REMOVE_LATER after downstream migration confirmation. |
| Legacy ST-12 domain DTOs and in-memory audit adapter | REMOVE_LATER | Not exported by the trusted package contract and cannot reach an active legacy service. | Remove in a dedicated duplication cleanup sprint. |

## Rules

- Deprecation never preserves an unsafe compatibility path.
- Deprecated paths cannot be re-enabled through flags or caller-supplied status strings.
- New clinical consumers must import the public governed contract from `jmoraIs.clinical`.
- Every clinical eligibility decision must resolve current lifecycle state.
- Every approval transition must pass reviewer authorization.
