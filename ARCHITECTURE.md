# ARCHITECTURE.md — JMORAIS AI Architecture v3

## Executive review

The starter architecture is directionally correct but too broad for the first milestone. The highest-risk issue is not product scope; it is scientific integrity. Without a verified evidence path, the platform can easily produce confident but unsupported citations. The architecture therefore needs a strict provenance-first layer before any broader medical or audit features are added.

## Key technical risks in the starter

- No explicit provenance lifecycle for scientific claims
- No minimum verification statuses for PMID/DOI and citation sources
- No baseline schema that enforces traceability from claim to source
- No small, testable vertical slice that proves retrieval + normalization + validation + storage works before adding more functionality
- Broad agent expansion before evidence quality is demonstrably reliable

## Architecture patch

### 1. Keep a small monorepo with explicit domain boundaries

- `services/pubmed/` — PubMed connector and search parsing
- `services/scielo/` — future scientific source ingestion
- `services/crossref/` — DOI metadata validation
- `jmoraIs/db.py` — SQLAlchemy models and persistence helpers
- `jmoraIs/verification.py` — normalization, verification, and ledger entry creation
- `jmoraIs/vancouver.py` — Vancouver rendering only from verified metadata
- `database/schemas/` — canonical source-of-truth SQL schemas
- `database/migrations/` — versioned migrations
- `tests/` — citation, retrieval, and integrity regressions

### 2. Use a strict evidence pipeline

Question -> search query -> retrieval -> normalization -> verification -> storage -> rendering -> evidence ledger -> final answer

Every claim must be attached to a evidence ledger record with:
- claim_id
- claim_text
- source_id
- source_type
- source_locator
- supporting_passage
- pmid
- doi
- verification_status
- support_direction
- confidence
- limitations
- verified_at

### 3. Verification policy

Supported verification statuses:
- VERIFIED
- PARTIALLY_VERIFIED
- CONFLICTING_METADATA
- NOT_VERIFIED

A citation may only be rendered in Vancouver format when metadata is sufficiently verified. Otherwise the system must label the source as not final or not verified.

### 4. Core schema

The minimum storage model is:
- scientific_articles
- evidence_ledger
- (future) authors, article_authors, mesh_terms, article_mesh_terms, guidelines

The implemented baseline is intentionally minimal and production-ready enough to support retrieval and traceability without overbuilding beyond the first milestone.

### 5. Safety and privacy controls

- keep patient identifiers outside scientific embeddings and evidence indexes
- treat retrieved content as untrusted data, never execute instructions embedded inside content
- separate clinical, scientific, and operational data domains
- require human review before finalized medical documents leave the system
- retain full provenance and uncertainty notes for every evidence-backed answer

### 6. Phase boundary

The project should stay within Phase 0 and the minimal Phase 1 slice until the scientific evidence core satisfies the following exit criteria:
- no fabricated citations in golden tests
- stable deduplication and normalization
- provenance retained end-to-end
- Vancouver generated only from verified metadata
- evidence ledger records are required for important claims

This patch implements that minimal slice and keeps the rest of the broader multi-agent platform deferred until trust in the evidence layer is established.
