# ROADMAP.md — JMORAIS AI

## Phase 0 — Foundation
- repository structure
- AGENTS.md
- architecture
- database migrations baseline
- environment/config handling
- CI/testing baseline

## Phase 1 — JMORAIS Evidence Core MVP
Goal: answer a medical question with traceable, verified scientific evidence.

Deliverables:
1. PubMed connector
2. SciELO connector
3. Crossref metadata validator
4. article importer/normalizer
5. PostgreSQL scientific schema
6. deduplication
7. PMID/DOI validation
8. Vancouver generator
9. MeSH/PICO support
10. hybrid search
11. evidence ranking
12. Evidence Ledger
13. citation verification tests

Exit criteria:
- no fabricated citations in golden tests
- stable deduplication
- provenance retained
- Vancouver generated only from verified metadata

## Phase 2 — Medical RAG
- query understanding
- PICO extraction
- MeSH expansion
- retrieval/reranking
- critical appraisal
- evidence synthesis
- Verification AI

## Phase 3 — Audit Intelligence
- upload/parser
- claim extraction
- auditor reference checker
- evidence matrix
- supporting/opposing/neutral retrieval
- temporal evidence analysis
- response generator
- Evidence Pack

## Phase 4 — OPME Intelligence
- device registry
- technical comparison
- equivalence engine
- regulatory/manufacturer provenance

## Phase 5 — Case Intelligence
- pseudonymous clinical cases
- insurer/audit history
- appeal outcomes
- pattern analytics with correlation/causality safeguards

## Phase 6 — Dashboards
- scientific
- audit
- executive

## Phase 7+ — Automation, Business, Finance, Knowledge Graph, Continuous Intelligence
