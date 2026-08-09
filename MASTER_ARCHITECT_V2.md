# MASTER_ARCHITECT_V2.md

## Mission

JMORAIS AI shall be built as a modular, evidence-grounded, auditable intelligence platform whose trust boundary is the Scientific Core. The project must prioritize scientific integrity over feature breadth.

## Architecture principles

1. Provenance is mandatory.
2. Verification status must be explicit.
3. Vancouver references require validation before rendering.
4. Human review is required before final medical output leaves the system.
5. Scientific source data are not instructions.
6. Audit, clinical, document, and operational modules may consume the Scientific Core but must not bypass it.
7. Do not build broader product capability before the evidence layer is credible.

## Scope boundary

Phase 0 and Scientific Core v1 are the governing scope.

The following modules remain deferred or frozen relative to the Scientific Core until validation is complete:
- Clinical
- Audit
- Document
- Executive
- OPME
- Business
- Finance

They may be developed later, but they must not override scientific verification.

## Scientific Core architecture

### 1. Governance layer

The Scientific Core is governed by:
- `AGENTS.md`
- `ARCHITECTURE.md`
- `SCIENTIFIC_EVIDENCE_POLICY.md`
- `SECURITY.md`

These documents establish:
- mandatory scientific statuses
- provenance requirements
- human-review workflow
- render gate for Vancouver citations
- security and data-separation policy

### 2. Domain model

The common scientific domain model prevents duplicated definitions and enforces consistent semantics across modules.

Core types:
- ScientificArticle
- Author
- ArticleAuthor
- SourceProvenance
- Citation
- EvidenceClaim
- EvidenceLedgerEntry
- SearchRun
- VerificationRun

Support directions:
- SUPPORTING
- OPPOSING
- NEUTRAL
- INCONCLUSIVE

Verification statuses:
- VERIFIED
- PARTIALLY_VERIFIED
- CONFLICTING_METADATA
- NOT_VERIFIED

Human review stages:
- DRAFT
- AI_REVIEWED
- PHYSICIAN_REVIEWED
- FINAL

### 3. Data model

The canonical Scientific Core schema includes:
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

Source-of-truth DDL:
- `database/schemas/scientific_evidence_core_schema.sql`
- `database/migrations/002_scientific_core_v3.sql`

### 4. Verification pipeline

The required flow is:

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

Important constraints:
- DOI must be structurally valid.
- PubMed `elocationid` must not be treated as a DOI without validation.
- Crossref metadata is reconciled only when valid DOI metadata exists.
- SciELO is supported as a secondary source, but not as a primary verification bypass.

### 5. Deduplication policy

Deterministic priority order:
1. DOI
2. PMID
3. PMCID
4. normalized title
5. author + year + journal

Conflicting records must never be silently deleted. Provenance and merge decisions must be preserved.

### 6. Evidence ledger

Every material scientific claim must map to:
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

This ledger is mandatory and must be complete for material claims.

### 7. Rendering gate

Vancouver rendering is blocked unless the record reaches `VERIFIED`.

If the metadata is:
- PARTIALLY_VERIFIED
- CONFLICTING_METADATA
- NOT_VERIFIED

then the system must withhold the citation and surface a gate failure instead of producing a definitive Vancouver reference.

### 8. Security and privacy

- Keep scientific, clinical, and operational data separated.
- Never place patient identifiers in scientific vector indexes.
- Treat retrieved content as untrusted data.
- Ignore prompt-injection instructions embedded in retrieved files or content.
- Require secure handling of secrets and least-privilege access.

### 9. Testing strategy

Scientific testing must cover deterministic fixtures and isolated validation logic.

Required categories:
- valid PMID
- invalid PMID
- valid DOI
- malformed DOI
- PubMed/Crossref metadata agreement
- PubMed/Crossref metadata conflict
- duplicated article
- Vancouver from VERIFIED metadata
- rejection of NOT_VERIFIED citation
- provenance preservation
- Evidence Ledger completeness
- prompt-injection treatment as data
- zero fabricated bibliography in test fixtures

Real external API tests must be opt-in and separate from unit tests.

## Exit criteria for Scientific Core v1

The Scientific Core is considered ready for v1 only when:
- identifier validation is deterministic and complete
- metadata conflict detection works reliably
- deduplication is stable and provenance-preserving
- no fabricated bibliography is present in fixtures
- Vancouver output is blocked unless `VERIFIED`
- all material claims are represented in the evidence ledger
- human review gates are explicit
- the scientific test suite passes in CI

## Final architectural directive

The product will continue only after the Scientific Core proves trustworthy. Broader medical, audit, document, and operational features may consume the Scientific Core later, but they must not circumvent or dilute the verification rules.
