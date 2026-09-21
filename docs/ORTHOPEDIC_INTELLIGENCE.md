# Orthopedic Intelligence — MIP-07

## Boundary

The bounded context `jmoraIs.orthopedic_intelligence` accepts only a governed, ready `ClinicalReasoningInput`. It resolves the referenced clinical state through `GovernedOrthopedicStateQueryPort`, active version-matched concepts through the terminology port, `GovernedEvidence`, and MIP-06 `GuidelineRecommendationSet`. Raw Patient Context, raw Clinical State, EvidencePackage, PubMed payloads, free text, dictionaries, connectors, and infrastructure objects are rejected.

The output is an immutable, reference-only `OrthopedicAssessmentSet`. It structures anatomical scope, laterality, problem status, severity, mechanical and stability findings, alignment, function, imaging concordance, evidence direction, guideline applicability, uncertainty, limitations, and decomposed confidence. It does not diagnose, recommend treatment, indicate surgery, predict outcomes, or reinterpret imaging.

## Safety and review

Suspected findings are never promoted. Unsupported severity becomes unknown and requires review. Laterality and source conflicts remain explicit. Imaging discordance is preserved. Human transitions reuse the canonical reviewer governance service. Reviewer approval never makes an assessment externally actionable while the platform-wide controlled-pilot restriction remains active.

## Persistence and audit

Assessment versions and audit events are append-only. Every later version links to its predecessor. PostgreSQL uses per-subject advisory locks, immutable JSONB snapshots, unique stream versions, and triggers rejecting UPDATE and DELETE. Audited events include generation, imaging/evidence/guideline correlation, conflicts, blocked boundaries, and review transitions.
