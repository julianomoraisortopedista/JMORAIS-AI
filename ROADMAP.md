# ROADMAP.md — JMORAIS AI

## Clinical Applications — Sprint S002 completed

SMART on FHIR authentication foundation: deterministic SMART/OIDC discovery,
JWKS/JWT verification, Authorization Code metadata, PKCE S256, scope parsing,
launch-context parsing and metadata-only append-only security audit. Hospital
transport, token exchange and clinical authorization remain deferred.

## Phase 2 active slice — MIP-06

Build the human-gated guideline recommendation engine over approved MIP-04 inputs and MIP-05 terminology. The slice provides deterministic applicability, validity, conflict detection, ranking, explainability and append-only history; autonomous clinical action remains prohibited.

## Phase 2 active slice — MIP-05

Establish the canonical terminology, coding, mapping, orthopedic vocabulary and UCUM normalization boundary. This slice provides immutable reference data and deterministic mapping only; guideline recommendations and clinical reasoning remain deferred.

## Phase 2 active slice — MIP-04

Establish the immutable Clinical Reasoning Input contract, its fail-closed readiness validation, governed review workflow, reference-only persistence and audit. No clinical reasoning engine or medical output is included.

## Phase 2 active slice — MIP-03

Build the derived Patient Clinical State and problem-list history from authorized Patient Context. This slice is limited to deterministic state representation, temporal reconstruction, explicit epistemic status, data-quality flags, review lifecycle and append-only persistence/audit. Medical decisions remain prohibited.

## Phase 2 active slice — MIP-02

Harden Patient Context with explicit data classification, pseudonymous identity separation, purpose/legal-basis authorization, deterministic de-identification, minimization, retention metadata, canonical typed ingestion and append-only privacy audit. This slice introduces no diagnosis, recommendation or autonomous reasoning.

## Phase 2 active slice — MIP-01

The Patient Context Engine establishes the canonical immutable patient-context aggregate, timeline, versioning services and repository boundary. Diagnosis, treatment, recommendations, RAG, LLM, embeddings and prediction remain explicitly deferred.

## Current gate: ST-22 Beta Readiness Hardening

Engineering scope includes Python 3.12 CI, PostgreSQL migrations/integration, persistent reviewer identity, least-privilege roles, integrity monitoring, backup/restore/replay, packaging cleanup and performance budgets. Beta remains blocked until the authoritative dataset meets minimum scale/diversity and its live workflow passes, restore evidence and performance measurements are captured, and production IAM/tenant isolation/deployment controls are validated.

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
## MIP-07 — Orthopedic Intelligence

Implemented as a governed structured-assessment layer. It is not a diagnostic, treatment, surgical-indication, prediction, LLM, or RAG engine. External patient-care use remains prohibited.

## MIP-08 — Medical Document Engine

Implemented as a deterministic, source-bound, append-only document composition layer with canonical review and validation. Procedure-justification and audit-support artifacts remain non-actionable drafts. PDF/DOCX, external identities and patient-facing delivery remain deferred.

## MIP-09 — Audit Defense AI

Implemented as a governed technical-support aggregation layer. It exposes supporting and opposing evidence, guideline conflicts, clinical limitations and deterministic counterarguments. It performs no payer authorization, autonomous medical decision or free-text generation.

## MIP-10 — Canonical LLM Gateway

Implements the exclusive provider boundary, canonical DTO validation, immutable prompt governance, non-actionable output classification, retries, cost accounting and privacy-preserving audit. Provider credentials and production transports remain deferred operational controls.
# Stage 14 status

The canonical LLM human-review boundary is implemented with immutable review events, active-lifecycle enforcement, canonical reviewer authorization, PostgreSQL RLS and restart-safe reconstruction. External clinical actionability remains explicitly out of scope.
