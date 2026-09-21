# Medical Document Engine — MIP-08

## Trust boundary and no fabrication

`jmoraIs.medical_documents` accepts only a ready `ClinicalReasoningInput` and resolves referenced facts through governed Patient Clinical State, terminology, evidence, guideline and orthopedic ports. It rejects raw Patient Context, raw EvidencePackage, connector payloads, dictionaries and free text. Missing information is rendered as `NOT_DOCUMENTED`, `NOT_AVAILABLE` or `REVIEW_REQUIRED`; it is never completed with plausible clinical content.

## Documents and templates

Supported types are clinical report, medical summary, follow-up report, surgical-history summary, orthopedic-assessment report, evidence summary, guideline summary, procedure-justification draft and audit-support draft. The last two remain drafts and cannot authorize procedures or payer actions. Immutable templates define section order, required and optional sections, allowed source types, formatting rules, policy and template versions.

## Attribution, citations and terminology

Every fact carries an epistemic status and canonical source/provenance references. Suspected and inferred facts remain explicitly labeled. Scientific sections accept only active `GovernedEvidence` and a canonical `VERIFIED` Vancouver rendering obtained through the Scientific Core citation port; the engine never constructs bibliographic truth. Guideline text comes only from MIP-06 output. Ambiguous or low-confidence terminology is surfaced for review.

Document terminology is resolved after restart through `GovernedDocumentTerminologyPort` backed by the canonical PostgreSQL terminology repository. This is a deterministic read projection: it neither duplicates terminology nor promotes inactive or ambiguous concepts. Terminology remains shared global reference data under its existing classification; tenant-scoped documents only retain governed concept references.

## Privacy, validation and review

Documents use pseudonymous patient references. Direct identity resolution and external identity rendering are not implemented. The validation gate blocks unsupported claims, medical decisions, missing references, invalid citations, hidden conflicts, direct-identifier leakage, incomplete required sections and missing provenance. Review transitions reuse canonical reviewer authorization. Approval does not make a document externally valid under the current controlled-pilot policy.

## Traceability, persistence and limitations

Every rendered section maps to source, terminology, policy and template references in a traceability manifest. JSON, plain-text and Markdown renderers are deterministic; PDF and DOCX are future adapters. Document versions, corrections and audit events are append-only in memory and PostgreSQL, with predecessor linkage, restart reconstruction and database rejection of UPDATE/DELETE.

The engine does not diagnose, prescribe, recommend treatment, indicate surgery, approve procedure justification, decide payer authorization, select OPME, use an LLM/RAG, expose a public API or resolve direct identities. Institutional validation, IAM, tenant isolation, identity vault, KMS and final LGPD governance remain deployment blockers.

Medical Document remains the authority over document identity and serialized
integrity. Stage 12 may retain only a canonical exact-version reference issued
from a persisted repository reread; it may not copy document prose or reinterpret
the document as Audit Defense evidence. See
`docs/STAGE11_STAGE12_TRACEABILITY.md`.

## Exact guideline-set ancestry

The controlled-pilot Stage 9→11 path receives an owner-issued `PersistedGuidelineRecommendationSetReference`, resolves it with `get_exact()` and persists that same typed reference in `MedicalDocumentVersion`. Individual recommendation IDs remain statement-level traceability. Documents without the reference are `LEGACY_MISSING_GUIDELINE_SET_REFERENCE` and cannot qualify as COMPLETE_CASE evidence. See `docs/GUIDELINE_SET_EXACT_TRACEABILITY.md`.
# Canonical scientific citation projection

Medical Documents resolve bibliography exclusively through `CanonicalDocumentCitationAdapter`, an implementation of the existing `CanonicalCitationQueryPort`. The adapter maps an active `GovernedEvidence` reference to its package and delegates restart-safe scientific validation to `ScientificCitationQueryPort`; it never queries connectors, the legacy `citations` table, or raw `ScientificArticle` data.

The resulting `DocumentEvidenceReference` preserves opaque scientific citation/package/publication identifiers, governed PMID/DOI/PMCID, the exact persisted Vancouver text and formatter version, provenance, ledger linkage, policy/version metadata and editorial status. `RETRACTED` and invalid/revoked packages fail closed; correction and editorial uncertainty remain explicit. Scientific citations are shared global reference data and contain no patient, tenant or case payload.
# Exact orthopedic lineage

The controlled-pilot path accepts an owner-issued
`PersistedOrthopedicAssessmentSetReference`, resolves the exact immutable set
through the Orthopedic Intelligence boundary, and persists the same reference.
It never selects `latest()` or reconstructs trusted identity from ID/version
scalars. Legacy rows without this reference are ineligible as COMPLETE_CASE
lineage evidence.
