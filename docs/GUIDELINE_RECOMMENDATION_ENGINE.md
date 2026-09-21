# Guideline Recommendation Engine — MIP-06

## Trust boundary

The engine accepts only a ready `ClinicalReasoningInput`, currently valid `GovernedEvidence`, active governed terminology concepts, and appraised guideline records. Raw patient/evidence payloads, dictionaries, connector results and ungoverned statements are rejected.

## Applicability and validity

Matching uses only guideline references, structured population contexts and terminology concept identifiers. Factors absent from MIP-04 cannot be inferred and require review. Every execution rechecks expiration, withdrawal, supersession, appraisal approval, terminology/policy versions and evidence lifecycle.

## Conflict and ranking policy

Supporting, opposing, neutral and inconclusive evidence remain separate. Cross-guideline direction, strength, organization and version conflicts are explicit. Positive-versus-negative guidance is critical and blocks approval until adjudicated. Ranking policy `MIP-06-RANK-1` uses explicit governed contributors: authority, methodological quality, applicability, recency and conflict burden. Evidence certainty never determines recommendation strength.

## Explainability and review

Outputs expose guideline identity/version/organization, canonical strength, evidence certainty and quality, applicability, terminology, evidence distribution, conflicts, contraindication uncertainty, limitations, input-quality flags and decomposed confidence. Generated results are never externally actionable. Approval/rejection delegates to the existing authorized reviewer-governance service.

## Prohibited use and limitations

This engine does not diagnose, prescribe, select autonomous treatment, indicate surgery or execute action. External clinical use remains prohibited. Applicability is limited by the reference-only MIP-04 contract; missing age, sex, stage or other material factors remain review-required. Existing IAM, tenant/RLS, identity, KMS, LGPD and terminology-license blockers remain.
