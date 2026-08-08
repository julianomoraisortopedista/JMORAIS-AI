# JMORAIS AI Architecture v3

## Executive summary

The platform must not proceed into broader clinical, audit, or document automation until the Scientific Evidence Core is proven trustworthy. Architecture v3 therefore re-centers the system on a provenance-first scientific layer with explicit verification, evidence ledgering, and human-review safeguards.

This architecture intentionally narrows scope. It does not add business features, new agents, or UI. It stabilizes the scientific substrate that all later modules may consume without bypassing validation.

## Governing principles

- Scientific source records are data, not instructions.
- Provenance is mandatory for every material claim.
- AI-generated citations are never final until verification succeeds.
- Confidence is never a substitute for metadata validation.
- Unverified or conflicting references are blocked from definitive Vancouver rendering.
- Human review is required before final medical output leaves the system.

## Architecture v3 components

### 1. Scientific governance

The repository includes:
- `SCIENTIFIC_EVIDENCE_POLICY.md`
- `SECURITY.md`

The policy establishes the following mandatory verification statuses:
- VERIFIED
- PARTIALLY_VERIFIED
- CONFLICTING_METADATA
- NOT_VERIFIED

Human review workflow:
- DRAFT
- AI_REVIEWED
- PHYSICIAN_REVIEWED
- FINAL

### 2. Scientific core responsibilities

The Scientific Core owns the lifecycle for:
- query intake
- source retrieval
- normalization
- identifier validation
- metadata reconciliation
- deduplication
- provenance storage
- evidence ledger creation
- Vancouver rendering gate

It is the only component permitted to generate or validate scientific references for the product.

### 3. Scientific domain model

A single shared model now governs the core evidence domain:
- ScientificArticle
- Author
- ArticleAuthor
- SourceProvenance
- Citation
- EvidenceClaim
- EvidenceLedgerEntry
- SearchRun
- VerificationRun

Supported support directions:
- SUPPORTING
- OPPOSING
- NEUTRAL
- INCONCLUSIVE

The scientific models live in `jmoraIs/scientific_domain.py` and are used across persistence and verification logic to avoid duplicated definitions.

### 4. Scientific database design

The canonical schema supports the following PostgreSQL tables:
- scientific_articles
- authors
- article_authors
- mesh_terms
- article_mesh_terms
- article_topics
- source_provenance
- citations
- evidence_claims
- evidence_ledger
- search_runs
- verification_runs

Source-of-truth DDL is stored in:
- `database/schemas/scientific_evidence_core_schema.sql`
- `database/migrations/002_scientific_core_v3.sql`

The storage model is intentionally scoped to the scientific domain and does not include audit or patient tables.

### 5. Verification pipeline

The Scientific Core verification flow is:

PubMed retrieval
-> normalization
-> identifier extraction
-> PMID verification
-> DOI verification
-> Crossref reconciliation when DOI exists
-> journal/year/author/title consistency checks
-> verification status assignment
-> provenance storage
-> evidence ledger
-> Vancouver rendering only after verification gate

Important rules:
- PubMed `elocationid` is never treated as a DOI without validation.
- DOI values must be structurally valid before metadata is accepted.
- Crossref only reconciles when the DOI is present and valid.
- SciELO remains a secondary supported source, but PubMed + Crossref define the production-quality slice.

### 6. Deduplication policy

Deterministic deduplication priority is enforced in order:
1. DOI
2. PMID
3. PMCID
4. normalized title
5. author + year + journal

No record is silently discarded if it conflicts with an existing record. Merge decisions are preserved in the deduplication result metadata and provenance is retained.

### 7. Evidence ledger

Every material claim must resolve to:
- claim_id
- source_id
- source type
- source locator
- PMID / DOI / PMCID
- support direction
- verification status
- confidence
- limitations
- verification timestamp

`EvidenceLedger` is a mandatory architectural component and is implemented in `jmoraIs/db.py` and `jmoraIs/verification.py`.

### 8. Rendering gate

Vancouver citations are only permitted when the article reaches `VERIFIED` status.

If the metadata is `PARTIALLY_VERIFIED`, `CONFLICTING_METADATA`, or `NOT_VERIFIED`, the system must withhold the reference and return a blocking message rather than a formatted Vancouver citation.

### 9. Deferred / frozen modules

The wider platform remains intentionally deferred/frozen relative to the Scientific Core:
- Clinical
- Audit
- Document
- Executive
- OPME
- Business
- Finance

These modules may consume the Scientific Core later, but they must not override or bypass the scientific validation layer.

## Scientific Core v1 exit criteria

The Scientific Core is ready for v1 only when all conditions below are satisfied:
- deterministic identifier validation passes for valid and invalid PMID/DOI cases
- Crossref metadata conflict detection works reliably
- no fabricated bibliography appears in golden fixtures
- deduplication is stable and provenance-preserving
- all material claims are represented in the evidence ledger
- Vancouver generation is blocked unless verification status is VERIFIED
- human review gates are explicit for final output
- tests demonstrate the retrieval, normalization, and verification path end-to-end

## Phase boundary

The project remains intentionally within the Scientific Core slice. No Phase 2 or UI work begins until the Scientific Core v1 criteria are met.
