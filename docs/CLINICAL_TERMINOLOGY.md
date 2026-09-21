# Clinical Terminology & Coding Layer — MIP-05

Mapping governance persistence is specified in
`docs/TERMINOLOGY_MAPPING_GOVERNANCE_PERSISTENCE.md`. `ClinicalConcept` deliberately
does not contain mapping confidence, review state or mapping policy version; those
belong to a separately versioned append-only governance record.

`jmoraIs.terminology` is the canonical bounded context for standardized clinical concepts, terminology versions, code mappings, relationships and deterministic UCUM normalization. Ambiguous mappings retain every candidate and return `REVIEW_REQUIRED`; unknown mappings never synthesize codes.

Supported code-system identities are ICD-10, ICD-11, SNOMED CT, LOINC, RxNorm, ATC, UCUM, TUSS, CPT as reference-only, and the governed JMORAIS orthopedic vocabulary. The repository does not redistribute licensed terminology content. Official releases must be acquired, licensed, checksummed, validated and loaded by an institutionally governed process.

Records and audit events are immutable and append-only. Deprecated, superseded and retired concepts remain reconstructable. The layer standardizes supplied concepts only and contains no diagnosis, treatment, recommendation, prediction, risk scoring or model-based interpretation.

Production blockers include terminology licenses, official distribution adapters, institutional mapping review, release-signature verification, locale governance, and the security/privacy prerequisites retained from MIP-02 through MIP-04.

Terminology now owns opaque exact references to persisted mapping-governance records. `reference_for(record)` validates canonical persistence and history; `get_exact(reference)` recomputes identity, policy, provenance, integrity and predecessor continuity. These references are shared global metadata and contain no clinical payload. See `docs/CLINICAL_REASONING_TERMINOLOGY_TRACEABILITY.md`.
