# JMORAIS-AI Platform Release Audit

**Audit date:** 2026-08-09
**Branch:** `feature/scientific-core-v0.2`
**Scope:** architectural release validation through ST-15
**Mode:** read-only validation of product code; this report is the only created artifact

## Executive conclusion

The platform has a credible and well-tested Scientific Core, a real EvidencePackage trust boundary, append-only scientific evidence history, fail-closed Vancouver rendering, an authoritative benchmark, and increasingly explicit clinical governance. These are substantial strengths.

The platform does **not**, however, satisfy all declared architectural invariants. Legacy clinical application paths can still consume a raw `EvidencePackage` without passing through appraisal governance; a legacy review service can transition recommendations without the ST-15 authorization port; governed-evidence re-evaluation is not enforced by the clinical eligibility gate; and the new governed persistence tables rely on ORM hooks rather than database-level append-only controls. These are direct trust-boundary and authorization blockers.

## Scores

| Area | Score | Assessment |
|---|---:|---|
| Architecture | 6.5/10 | Strong direction and boundaries, but legacy bypass paths and stale governing documentation remain. |
| DDD | 6.0/10 | Bounded contexts exist, but duplicated domain concepts and mutable legacy/scientific entities weaken the model. |
| Clean Architecture | 6.5/10 | Ports and adapters are visible; public exports and legacy application paths undermine exclusivity. |
| Scientific Integrity | 8.5/10 | Authoritative verification, reconciliation, provenance, package boundary, ledger and citation gates are strong. |
| Clinical Integrity | 6.0/10 | Governed pipeline is sound in isolation, but enforcement is not universal and re-evaluation is not coupled to eligibility. |
| Security | 5.5/10 | Fail-closed checks exist, but authorization bypasses, incomplete replay verification and ORM-only immutability are material gaps. |
| Test maturity | 8.0/10 | High measured coverage and extensive negative tests; real PostgreSQL and online integrations were not executed. |

## Validation evidence

### Test execution

- Standard suite: **228 passed, 9 skipped, 1 warning** in 1.59 seconds.
- Coverage run: **228 passed, 9 skipped, 1 warning**.
- Measured coverage: **91%** across `jmoraIs` and `evaluation.scientific_benchmark` (3,226 statements; 293 missed).
- PostgreSQL integration: **not executed**, because `JMORAIS_TEST_POSTGRES_URL` is not configured.
- `git diff --check`: **PASS**.
- Runtime warning: local Python 3.9/LibreSSL is not a supported urllib3 v2 TLS configuration.

Coverage is strong for core application logic. Important weak spots include the online benchmark clients (37%), in-memory governance adapters (38%), PubMed connector (69%), connector base (77%), configuration (78%), and the unused embeddings module (0%). Coverage does not replace live service, PostgreSQL concurrency, migration, or tamper-resistance validation.

## Architectural checklist

| Invariant | Result | Evidence and impact |
|---|---|---|
| No circular dependencies | PASS | Static module graph analysis found no cycles among `jmoraIs` modules. |
| No infrastructure leakage | PARTIAL | Core application services generally use protocols, but package `__init__` files export concrete in-memory and SQLAlchemy adapters alongside domain/application contracts. |
| No mutable domain entities | FAIL | 21 non-frozen dataclasses exist, including `ScientificArticle`, `SourceProvenance`, `Citation`, `EvidenceClaim`, `SearchRun`, `ClinicalCase` and legacy clinical recommendations. |
| No direct connector access by consumers | PASS | Architecture tests and static inspection found no connector import from the governed clinical pipeline. |
| No Scientific Core bypass | PARTIAL | Governed flow uses EvidencePackage correctly, but legacy connector/service layers and direct low-level imports remain available within the repository. |
| No governance bypass | FAIL | `jmoraIs.clinical.application.ClinicalIntelligenceService` consumes raw EvidencePackage IDs and remains importable; `jmoraIs/clinical_engine.py` does the same. |
| No human-review bypass | FAIL | `RecommendationReviewService` is publicly exported and accepts only a reviewer ID string, bypassing `ReviewerAuthorizationPort`. |
| No raw EvidencePackage reaching Clinical Intelligence | FAIL | The ST-14 public alias is governed, but two importable legacy clinical engines still accept EvidencePackage directly and are exercised by tests. |
| No raw PubMed reaching recommendation engine | PASS | No PubMed connector or raw retrieval result is imported by governed clinical or appraisal modules. |
| No hidden mutable state | PARTIAL | Domain additions are frozen, but in-memory repositories use mutable dictionaries/lists and several legacy domain objects remain mutable. |
| No duplicated domain concepts | FAIL | Duplicates include `EvidenceLevel`, `ClinicalRecommendation`, `EvidencePackageQueryPort`, scientific domain/ORM names, and two clinical audit/review families. |
| No duplicated business rules | FAIL | Evidence weighting, confidence scoring, conflict handling and review transitions exist in both ST-12 and governed ST-14/ST-15 implementations. |

## Component findings

### Scientific Core

**PASS with operational limitations.** Identifier format validation is separated from authoritative existence checks. PubMed is primary for PMID, Crossref reconciles DOI where applicable, conflicts are preserved, deduplication is deterministic, and provenance is retained. Internal `EligibleEvidenceResult` remains correctly scoped to the scientific application pipeline and is not the trusted public result.

Risks:

- Scientific domain dataclasses are mutable, making verified state alterable inside the process.
- Connector implementations contain long methods and mutable authoritative metadata dictionaries.
- Two connector families exist: `jmoraIs.connect.*` and `services.*`; the latter can bypass the canonical connector/application composition if reused.
- `services.crossref` and `services.scielo` are not included in setuptools package declarations.

### EvidencePackage and Scientific Ledger

**PASS for implemented in-memory/adapter behavior; PARTIAL for production proof.** EvidencePackage is frozen, integrity-hashed, provenance-linked, ledger-linked, and revalidated against lifecycle history. Retraction, invalidation and supersession revoke packages without destructive mutation. The ledger uses hash-chained events and supports temporal reconstruction.

Risks:

- A real PostgreSQL run was unavailable.
- Canonical ledger reconstruction reloads the complete stream when a PostgreSQL package is resolved.
- Application-level integrity depends on SHA-256 hashes without an external signature or protected key.

### Citation Verification

**PASS.** Only `VERIFIED` package-backed metadata reaches strict Vancouver formatting. Partially verified, conflicting, unverified, incomplete, free-form and model-produced citations are blocked. Formatter versioning is present.

### Authoritative Benchmark

**PARTIAL.** The benchmark uses real PMID, PMCID and DOI records with PubMed, PMC, Crossref, OpenAlex and optional Semantic Scholar support. It calculates precision, recall, false-positive/negative rates and coverage.

Limitations:

- Only three positive publications are present, all from one journal family.
- Statistically meaningful negative, retracted, corrected and cross-language cases are absent.
- Online clients were skipped in the standard suite.
- Source client test coverage is 37%.

### Clinical Appraisal

**PASS in isolation.** Immutable appraisal entities represent methodological quality, evidence hierarchy, recommendation strength, guideline governance, applicability, validity and conflict resolution. Invalid or conflicting results are marked ineligible.

Limitations:

- Appraisal inputs are caller-supplied rather than produced by a reviewer-attributed appraisal workflow.
- Guideline authority is a free-form organization string rather than a governed registry.
- Effective supersession dates are not represented.

### Governed Evidence

**PARTIAL.** `GovernedEvidence` is immutable, integrity-protected, references the source package rather than copying scientific payloads, and has append-only SQLAlchemy version storage.

Critical issue:

- The re-evaluation service can append `REVIEW_REQUIRED` or `INVALIDATED`, but `GovernedEvidenceEligibilityGate` does not query lifecycle history. A guideline that expires after issuance may still be consumed clinically unless a separate caller invokes and enforces re-evaluation. The trust decision is therefore orchestration-dependent rather than intrinsic to the boundary.

Persistence issues:

- Migration 005 has no PostgreSQL triggers denying UPDATE/DELETE. Immutability is enforced only through SQLAlchemy `before_flush`, so raw SQL can alter history.
- Audit, conflict and lifecycle replay deserialize stored hashes but do not recompute every event hash from its payload and previous hash.
- Stream version allocation uses `len(history) + 1`; concurrent writers can race. The SQLAlchemy table metadata lacks the migration's unique `(evidence_package_id, stream_version)` constraint.

### Clinical Intelligence and Human Review

**FAIL as an exclusive platform boundary.** The governed pipeline correctly rejects raw objects, expired/withdrawn/superseded governance, missing trust links, incompatible applicability and unresolved critical conflicts. It preserves all four evidence directions, explainability and mandatory pending review.

Blocking bypasses:

- `jmoraIs.clinical.application.ClinicalIntelligenceService` still accepts EvidencePackage IDs plus caller-declared appraisal weights.
- `jmoraIs/clinical_engine.py` still accepts EvidencePackage IDs directly.
- Both paths avoid `GovernedEvidenceEligibilityGate`.
- `RecommendationReviewService` remains exported and can approve with an arbitrary non-empty reviewer ID, bypassing the authorized ST-15 review service.

### Reviewer Governance and Conflict Adjudication

**PARTIAL.** Reviewer identity, roles, authorization port, self-approval policy, senior-review requirement, immutable transitions, attribution and conflict states exist. Persistent adapters are replayable in SQLite tests.

Limitations:

- The authorization adapter is in-memory and not backed by an authoritative identity provider.
- Recommendation state is returned as a new object but is not itself stored as a canonical projection; audit replay must reconstruct it externally.
- Critical conflict adjudication is not connected back to a new GovernedEvidence version or clinical eligibility automatically.

## DDD and Clean Architecture findings

Strengths:

- Scientific, appraisal and clinical governance concepts have identifiable boundaries.
- Application services depend on repository/query protocols.
- SQLAlchemy adapters do not leak into the main governed application services.
- Domain additions from ST-12 onward are predominantly frozen value objects.

Debt:

- ORM entities and domain entities share names (`ScientificArticle`, `Author`, `Citation`, `EvidenceClaim`, `SearchRun`, `VerificationRun`) without explicit persistence suffixes everywhere.
- `EvidenceLevel` exists independently in clinical and appraisal domains with different members and ordering.
- `ClinicalRecommendation` exists in `clinical_engine.py` and `clinical/domain.py`, while `GovernedClinicalRecommendation` is a third model.
- `EvidencePackageQueryPort` is repeated in three modules rather than being a shared stable contract.
- In-memory and persistent repositories are exported from bounded-context root packages, mixing application API with composition concerns.
- Legacy and governed recommendation services implement overlapping weighting, conflict, confidence, audit and review logic.

## Code quality findings

### Complexity and cohesion

Thirteen functions exceed 40 lines. Highest-risk examples:

- `ScientificEvidencePackagePort.issue`: 118 lines.
- `AppendOnlyEvidenceLedger.register_evidence`: 111 lines.
- `PubMedConnector.search_by_pmid`: 78 lines.
- `CrossrefConnector.search_by_doi`: 74 lines.
- `decide_publication_verification`: 67 lines.
- Legacy clinical `_recommend`: 57 lines.
- `GovernedEvidenceService.issue`: 51 lines.

These methods combine validation, transformation, policy decisions and construction, increasing change risk.

### Dead or deferred code candidates

- `jmoraIs/embeddings.py` has 0% coverage and introduces ChromaDB/NumPy despite RAG being deferred.
- `services/pubmed`, `services/crossref` and `services/scielo` duplicate connector responsibilities outside the canonical Scientific Core connectors.
- Legacy clinical foundation/application paths overlap the governed pipeline.
- Multiple in-memory repository implementations represent successive sprint versions rather than one canonical adapter family.

### Naming and packaging

- Project/module spelling `jmoraIs` is unconventional and case-sensitive.
- `pyproject.toml` declares Python `>=3.10`, while the governing project direction specified Python 3.12 and the audit ran under Python 3.9.6.
- `requirements.txt` includes ChromaDB and NumPy, but `pyproject.toml` omits them.
- Setuptools explicitly packages only `services.pubmed`, excluding `services.crossref`, `services.scielo`, and benchmark tooling.
- Documentation references source-of-truth paths and a frozen Clinical phase that no longer match the implemented repository state.

## Security assessment

### Effective controls

- Scientific and appraisal boundaries fail closed on missing or malformed trust links.
- EvidencePackage and GovernedEvidence integrity hashes are checked at resolution.
- Scientific ledger and audit events link previous hashes.
- Reviewer role and self-approval policy exist in the authorized path.
- External scientific payloads are not treated as instructions in the governed recommendation path.

### Security blockers

- Legacy clinical and review exports bypass governance/authorization.
- New governed persistence is not database-enforced append-only.
- Audit/conflict/lifecycle repositories do not perform complete cryptographic replay verification.
- Hashes are unkeyed and have no external anchoring, signature, or immutable storage attestation.
- There is no real authentication provider, secret-management validation, authorization integration, or database least-privilege proof.
- No security tests demonstrate raw SQL tamper resistance for governed history.

## Performance assessment

- Clinical evaluation deduplicates governed IDs within a request, avoiding duplicate application-level resolution in that call.
- PostgreSQL package resolution reconstructs the canonical ledger repeatedly; multiple packages can produce full-ledger replay per package.
- Audit append calls load complete case history to obtain the last hash; persistent append then loads it again.
- GovernedEvidence version append loads the entire version history to calculate the next version.
- In-memory package lookup by ID is constant time, but lookup by EvidencePackage ID is linear.
- JSON payloads duplicate complete immutable events and version data, increasing storage and serialization cost.
- No pagination, snapshotting, checkpointing, batch resolution, optimistic concurrency or performance benchmarks exist.

## Technical debt priority

### P0 — release blockers

1. Remove or permanently fail-close every raw-EvidencePackage clinical path; preserve one governed public and internal pipeline.
2. Remove the unauthenticated `RecommendationReviewService` path and expose only authorized review transitions.
3. Make lifecycle/re-evaluation status mandatory inside GovernedEvidence resolution or the eligibility gate.
4. Add PostgreSQL-level append-only triggers and constraints for all ST-15 tables.
5. Recompute and verify event hashes and complete chains during every audit/conflict/lifecycle replay.
6. Run migrations and integration tests against an actual PostgreSQL instance, including concurrent writers and raw SQL mutation attempts.

### P1 — architectural hardening

1. Consolidate duplicated evidence levels, recommendation models, ports and repository families.
2. Separate ORM record names from domain entity names and formalize mapping boundaries.
3. Make scientific domain state transitions immutable or aggregate-controlled.
4. Connect resolved conflict events to a new GovernedEvidence version and mandatory human re-review.
5. Persist/reconstruct the canonical recommendation review projection.
6. Align architecture, roadmap, security, README and packaging metadata with the implemented platform.

### P2 — maintainability and scale

1. Decompose long orchestration methods into cohesive policies and factories.
2. Remove or quarantine deferred embeddings/RAG code.
3. Remove duplicate legacy service connectors after confirming no consumers.
4. Add pagination, latest-event queries, batch package resolution and replay checkpoints.
5. Expand the authoritative benchmark and add performance, migration and recovery benchmarks.

## Known limitations

- No patient-context, RAG, LLM, API, frontend, OPME or autonomous clinical decision functionality was evaluated or added.
- No real PostgreSQL instance was available.
- No external biomedical APIs were invoked during this release audit.
- Authentication, SSO, secrets management, deployment, backup, disaster recovery and observability are not production implementations.
- The worktree contains extensive uncommitted changes, so the audited state is not an immutable or reproducible release artifact.

## Risk assessment

| Risk | Severity | Likelihood | Release effect |
|---|---|---|---|
| Clinical governance bypass through legacy service | Critical | High | Blocks release certification. |
| Reviewer authorization bypass | Critical | High | Blocks release certification. |
| Stale governed evidence accepted after guideline lifecycle change | Critical | Medium | Blocks release certification. |
| Governed history altered through raw SQL | High | Medium | Blocks production and RC claims. |
| Audit tampering not detected during replay | High | Medium | Blocks production-grade audit claims. |
| PostgreSQL migrations/replay unvalidated | High | Medium | Blocks durable-release claims. |
| Mutable and duplicated domain models | Medium | High | Increases defect and divergence risk. |
| Full-stream replay and N+1 behavior | Medium | Medium | Limits scale; does not alone block alpha testing. |
| Stale documentation and packaging | Medium | High | Prevents reproducible release/build governance. |

## Recommendations

1. Execute a dedicated trust-boundary consolidation sprint addressing every P0 item without adding medical functionality.
2. Add architectural tests that fail if any clinical module imports `EvidencePackage` or exposes an unauthenticated review service.
3. Make governed lifecycle status part of the same atomic resolution used by Clinical Intelligence.
4. Enforce append-only behavior in PostgreSQL itself and validate it with real integration tests.
5. Introduce full replay verifiers for governed audit, conflict and lifecycle streams.
6. Remove legacy models and rules only after migration tests prove the governed replacement.
7. Re-run this audit from a clean, committed release branch with Python 3.12 and configured PostgreSQL.

## Release decision

# NOT READY

The platform is not eligible for ALPHA, BETA, RELEASE CANDIDATE or production classification under its own architectural checklist. The Scientific Core is comparatively mature, but the platform-level trust boundary is not exclusive: raw EvidencePackage clinical paths and an unauthenticated reviewer path remain available, governed lifecycle decisions are not intrinsically enforced, and durable audit immutability has not been proven in PostgreSQL. A green test suite and 91% coverage do not compensate for these explicit invariant failures.
