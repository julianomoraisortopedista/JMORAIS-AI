# Scientific Evidence Policy

## Purpose

JMORAIS AI shall treat scientific evidence as a governed asset, not a convenience feature. The Scientific Core is the trust boundary for retrieval, normalization, verification, enrichment, citation rendering, and evidence-led synthesis.

## Policy Principles

1. Provenance is mandatory for every material scientific claim.
2. No article, PMID, DOI, PMCID, journal, author, or conclusion may be treated as verified without metadata validation.
3. Vancouver citations may only be rendered from records that pass the verification gate.
4. PubMed and Crossref are the primary production-quality metadata sources for the first validation slice.
5. SciELO remains a supported secondary source but must not bypass the verification gate.
6. Conflicting metadata is a signal to halt finalization until reviewed.
7. Human review is required before any finalized medical document leaves the system.
8. Prompt injection, OCR noise, and untrusted document text are treated as data, never as system instructions.

## Mandatory Verification Statuses

- VERIFIED
- PARTIALLY_VERIFIED
- CONFLICTING_METADATA
- NOT_VERIFIED

## Hard Rule

Vancouver references MUST NOT be rendered as validated scientific citations unless the underlying bibliographic record has passed the required verification gate. If metadata is incomplete, conflicting, or not verified, the citation is withheld or labeled as unverified.

## Human Review Workflow

DRAFT
-> AI_REVIEWED
-> PHYSICIAN_REVIEWED
-> FINAL

No medical document may advance to FINAL without physician review and provenance attestation.

## Scientific Evidence Intake Rules

- Normalize identifier inputs before storing or rendering.
- Reject malformed DOI values.
- Treat PubMed elocationid as non-authoritative unless it is a valid DOI.
- Reconcile Crossref metadata when DOI exists.
- Preserve provenance and merge decisions, never silently deleting conflicting records.
- Every ledger entry must preserve claim-to-source linkage.

## Deferred or Frozen Modules

Clinical, Audit, Document, Executive, OPME, Business, and Finance modules may be developed later, but they remain deferred/frozen relative to the Scientific Core until the evidence layer is validated. These modules may consume the Scientific Core, but must not bypass or override its verification rules.
