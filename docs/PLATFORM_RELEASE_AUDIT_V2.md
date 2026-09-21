# JMORAIS-AI Platform Release Audit v2

**Audit date:** 2026-08-09
**Branch:** `feature/scientific-core-v0.2`
**Audited runtime:** Python 3.12.13 / PostgreSQL 16.14
**Scope:** platform state after ST-18, ST-19, ST-20 and ST-21
**Mode:** read-only product audit; this report is the only repository artifact created

## Executive summary

JMORAIS-AI has progressed from **NOT READY** to **ALPHA**. The P0 findings from the
previous platform audit are materially resolved: the clinical trust path is
exclusive and fail-closed, deprecated clinical/review paths are tombstones,
governed lifecycle state is enforced at eligibility time, PostgreSQL protects
immutable history against normal `UPDATE` and `DELETE`, concurrent stream writes
are serialized and collision-protected, and cryptographic replay independently
recomputes event hashes and validates append-only completeness checkpoints.

This is a credible scientific and clinical-governance foundation, not a
production medical platform. It is not BETA, RELEASE CANDIDATE, or production-ready
because the audited implementation exists almost entirely as uncommitted work,
there is no versioned CI/release evidence, live biomedical integrations were not
executed, the benchmark remains narrow, authentication and authoritative reviewer
identity are not implemented, operational controls are absent, documentation and
packaging metadata drift from the code, and regulatory readiness is not established.

## Scores

| Area | Score | Basis |
|---|---:|---|
| Architecture | 8.4/10 | Exclusive governed path, explicit trust boundaries, cohesive ports and architecture tests; composition and release packaging remain immature. |
| DDD | 8.1/10 | Canonical scientific, appraisal, governed-evidence and reviewer concepts; two documented mutable working aggregates and ORM naming debt remain. |
| Clean Architecture | 8.3/10 | Domain/application layers remain PostgreSQL-agnostic and adapters implement ports; bounded-context roots still export concrete adapters. |
| Scientific Integrity | 8.8/10 | Authoritative existence verification, reconciliation, provenance, EvidencePackage, ledger and strict Vancouver gate are strong; live benchmark breadth is insufficient. |
| Clinical Integrity | 8.4/10 | GovernedEvidence-only reasoning, lifecycle eligibility, explainability, conflict handling and mandatory authorized review are enforced. Appraisal inputs and reviewer directory are not institutionally governed. |
| Security | 7.3/10 | Strong integrity and fail-closed controls; no production IAM, role deployment, secret-store validation, external cryptographic anchor, security monitoring or incident workflow. |
| Persistence | 9.0/10 | Alembic, real PostgreSQL, foreign keys, constraints, append-only triggers, restart and reconstruction are proven. Backup/restore and production-role grants are not. |
| Concurrency | 8.8/10 | Advisory locks, unique positions/versions, typed conflicts and controlled retry are tested with real concurrent writers. No sustained load or failure-injection benchmark exists. |
| Cryptographic Integrity | 8.5/10 | Genesis recomputation, complete chains, tail checkpoints and binary reports are proven. Hashes/checkpoints share one administrative boundary and are not externally signed. |
| Test Maturity | 9.0/10 | 251 passing tests, real PostgreSQL, negative trust tests and 90% coverage. Eight external biomedical tests remain opt-in. |
| Operational Readiness | 4.2/10 | Reproducible local containers exist, but CI/CD, deployment, monitoring, backup, recovery, SLOs and runbooks do not. |
| Documentation | 6.6/10 | Sprint hardening documents are strong; README, ROADMAP, architecture phase statements, security controls and packaging metadata are stale or incomplete. |

## Validated invariants

### Scientific Core

| Invariant | Result | Evidence |
|---|---|---|
| Identifier format is not verification | PASS | Format validation cannot produce `VERIFIED`; authoritative PMID/DOI outcomes are mandatory. |
| PubMed/Crossref reconciliation is canonical | PASS | Application pipeline reconciles metadata, retains conflicts and prevents connector bypass through architecture tests. |
| Deduplication is deterministic and traceable | PASS | DOI/PMID/title rules and merge decisions are preserved with provenance. |
| EvidencePackage is the trust boundary | PASS | Arbitrary dictionaries, forged states and internal eligibility results are rejected. |
| Citation Verification Gate fails closed | PASS | Only valid `VERIFIED` packages produce final Vancouver output; free-form/model text is blocked. |
| Scientific ledger is append-only and replayable | PASS | Domain invariants, PostgreSQL triggers, hash chains and checkpoints are tested. |
| Authoritative benchmark | PARTIAL | Real authoritative identifiers and multi-source clients exist, but the live suite was not enabled and the dataset is too small for release claims. |

### Clinical trust boundary

The only supported trusted path is:

`Scientific Core → EvidencePackage → Appraisal → GovernedEvidence → Lifecycle-aware Eligibility Gate → Governed Clinical Intelligence → Authorized Human Review`

- Public `ClinicalIntelligenceService` aliases the governed implementation.
- Legacy clinical engine/application entry points raise fail-closed deprecation errors.
- Raw PubMed records, raw EvidencePackages, dictionaries and caller-provided
  `verification_status` values cannot enter governed Clinical Intelligence.
- The unauthenticated review service is a tombstone and is not publicly exported.
- Recommendations remain non-actionable until an authorized review transition.

Result: **PASS** for the implemented platform boundary.

### Domain consolidation

- Canonical `VerificationStatus`, `SupportDirection`, `EvidenceLevel`,
  `RecommendationStrength`, reviewer roles and package query port are unique.
- Domain dataclasses are frozen except `ScientificArticle` and `SearchRun`, whose
  controlled construction-time mutation is documented and architecture-tested.
- Legacy clinical domain/repository implementations were removed.
- Deprecated services contain no parallel recommendation, eligibility or review rules.

Result: **PASS with documented debt**.

### Reviewer governance

- Typed reviewer identity and roles: PASS.
- Authorization abstraction: PASS.
- Senior reviewer required for critical conflict resolution: PASS.
- Self-approval blocked by policy: PASS.
- Immutable, attributed audit transitions: PASS.
- Human approval required for external actionability: PASS.
- Production identity provider and persistent authoritative reviewer directory: NOT IMPLEMENTED.

### Lifecycle governance

The platform represents and enforces `ACTIVE`, `REVIEW_REQUIRED`, `SUPERSEDED`,
and `INVALIDATED`. Tests cover propagation from package revocation, guideline
expiration/withdrawal/supersession, appraisal version changes, policy changes and
critical conflict changes. Eligibility resolves current lifecycle state instead
of trusting an issuance-time cache.

Result: **PASS**.

### Persistence and concurrency

- Alembic migrations 004–007 applied on PostgreSQL 16.14: PASS.
- Raw SQL `UPDATE` and `DELETE` rejection: PASS.
- Foreign keys, uniqueness, positive position/version and state constraints: PASS.
- Restart, package recovery and historical reconstruction: PASS.
- Transaction-scoped advisory locking per logical stream: PASS.
- Concurrent GovernedEvidence version allocation: PASS.
- Concurrent lifecycle and clinical audit append: PASS.
- Duplicate positions/versions and stale hashes fail closed: PASS.
- Controlled reload/rebuild/retry behavior: PASS.

### Cryptographic replay

- Genesis-to-head SHA-256 recomputation: PASS.
- Stored payload/hash distrust: PASS.
- Previous-hash and complete-chain validation: PASS.
- Missing intermediate and final event detection: PASS.
- Duplicate, insertion and reordering detection: PASS.
- Timestamp monotonicity: PASS.
- Version continuity: PASS.
- Provenance/ledger linkage: PASS.
- Independent append-only completeness checkpoint: PASS.
- Platform-wide aggregate report: PASS.
- Decision vocabulary limited to `VALID` or `TAMPERED`: PASS.

## Test results

Command executed inside the reproducible Python 3.12 container with
`JMORAIS_TEST_POSTGRES_URL` targeting the isolated PostgreSQL service:

`python -m pytest -q --cov=jmoraIs --cov-report=term`

| Metric | Result |
|---|---:|
| Python | 3.12.13 |
| PostgreSQL | 16.14 |
| Passed | 251 |
| Failed | 0 |
| Skipped | 8 |
| Warnings | 0 |
| Coverage | 90% |
| Statements | 3,032 |
| Missed statements | 299 |
| `git diff --check` | PASS |

All PostgreSQL ST-20/ST-21 tests executed. The eight skips are external biomedical
API tests requiring `JMORAIS_RUN_AUTHORITATIVE_BENCHMARK=1` or an explicit live
integration setting; they are not PostgreSQL skips.

## Security assessment

### Application integrity

Strong controls include typed trust artifacts, immutable domain outputs, integrity
validation on resolution, lifecycle-aware eligibility, fail-closed citation and
clinical boundaries, authorization policy, and negative bypass tests.

Residual risks:

- reviewer identities use an in-memory adapter rather than an authoritative identity source;
- audit/document/executive legacy utility modules accept generic dictionaries but
  are outside the governed trusted clinical path;
- security-specific prompt-injection and malicious-document suites are not mature;
- structured operational logging and alerting are not implemented.

### Database integrity

PostgreSQL itself enforces append-only history, referential integrity, unique stream
positions, transaction ordering and checkpoint creation. Raw SQL mutation and
concurrent collision tests pass. This is materially stronger than ORM-only control.

Residual risks:

- production database roles and grants have not demonstrated least privilege;
- backup/restore, point-in-time recovery and disaster-recovery replay are untested;
- no production retention, capacity or migration rollback runbook exists.

### Fully privileged database administrator

SHA-256 chains and checkpoints detect the tested historical mutations as long as
the checkpoint boundary remains trustworthy. A fully privileged administrator can
disable triggers and consistently rewrite events, hashes and checkpoints. The
current design has no external signature, HSM-backed key, transparency log,
write-once storage or independently operated anchor. Therefore it provides strong
application/database integrity, not proof against total database-administrator
compromise.

### Secrets and attack surface

- Static search found no committed API key, token or production password assignment.
- Docker credentials are explicitly local test-only values.
- Runtime secrets are environment-driven.
- There is no public API, authentication provider, frontend or deployment surface yet.
- Dependency scanning, SBOM, container scanning and secret-scanning CI are absent.

## Repository hygiene

### Blocking release-artifact findings

- The branch matches `origin/feature/scientific-core-v0.2` at commit `7fdf902`, but
  nearly all ST-18–ST-21 implementation and tests are uncommitted/untracked.
- The audited state cannot be reproduced from the remote commit or identified by a
  release tag.
- No versioned `.github/workflows` CI pipeline is present.
- The `.git/index.lock` file exists and should be investigated before Git operations.

### Documentation and packaging drift

- README still describes only the initial Phase 0/Phase 1 slice and Python virtualenv
  workflow, not the governed clinical and PostgreSQL replay platform.
- ROADMAP and architecture documents still describe Clinical as frozen/deferred,
  despite implemented appraisal and governed clinical foundations.
- SECURITY does not document ST-20/ST-21 controls, database-admin limitations,
  reviewer authorization, concurrency or checkpoints.
- `pyproject.toml` correctly requires Python 3.12 but explicitly packages only a
  subset of modules; benchmark, Crossref and SciELO service packages are omitted.
- `requirements.txt` includes deferred ChromaDB/NumPy while `pyproject.toml` does
  not; `jmoraIs/embeddings.py` remains at 0% coverage although RAG is deferred.

## Production-readiness dimensions

| Dimension | Assessment | Release implication |
|---|---|---|
| Architecture readiness | Strong ALPHA | Trust path and boundaries are technically coherent. |
| Scientific readiness | ALPHA | Core verification is strong; benchmark/live-source validation is not broad enough for BETA claims. |
| Clinical governance readiness | Strong ALPHA | Correct governed flow exists; institutional reviewer identity and real clinical validation are absent. |
| Database readiness | BETA-level foundation | Integrity/concurrency are proven locally; backup, roles, recovery and performance remain. |
| Security readiness | ALPHA | Strong integrity controls but no production IAM, external anchor, security operations or deployment hardening. |
| Operational readiness | Pre-ALPHA | No CI/CD, deployment, observability, SLOs, backup/DR or incident runbooks. |
| Regulatory readiness | NOT READY | No LGPD data map/DPIA, clinical safety case, intended-use classification, validation protocol, change control or regulatory dossier. |

## Unresolved blockers

### Blocks BETA

1. Commit and review the complete audited change set; produce a clean, tagged,
   reproducible release artifact.
2. Add mandatory CI on Python 3.12 with PostgreSQL migrations, concurrency,
   cryptographic replay, architecture tests, coverage and `git diff --check`.
3. Execute and retain results for the live authoritative benchmark; expand it with
   retracted, corrected, negative, conflicting, multilingual and diverse-journal cases.
4. Replace the in-memory reviewer directory with an authoritative, persistent
   authorization adapter while preserving the existing port and policies.
5. Align README, ROADMAP, ARCHITECTURE, SECURITY and packaging metadata with the
   actual platform and remove ambiguous source-of-truth declarations.
6. Define database roles/grants and prove least privilege for application,
   migration and audit/replay identities.
7. Add baseline structured logging, integrity alerts and redaction tests.

### Blocks RELEASE CANDIDATE

1. Deployment automation with immutable images, environment promotion and rollback.
2. Backup, restore, PITR and disaster-recovery replay exercises.
3. Performance/load benchmarks for large ledgers, checkpoints, package resolution
   and concurrent clinical/audit streams.
4. External cryptographic anchoring or an explicitly accepted database-admin threat
   limitation backed by governance and monitoring.
5. Dependency/SBOM, vulnerability, container and secret scanning gates.
6. Production-grade observability, SLOs, incident response and integrity runbooks.
7. Representative clinical validation with documented human-review protocols.

### Blocks production

1. Formal intended use and regulatory classification.
2. LGPD data inventory, lawful basis, DPIA, retention/deletion policy, data-subject
   workflows and processor/vendor governance.
3. Clinical safety case, hazard analysis, validation protocol, usability controls,
   post-market monitoring and accountable medical governance.
4. Authentication/SSO, authorization administration, audit access controls and
   production secret/key management.
5. Independent security assessment and production penetration testing.

## Technical debt

- `ScientificArticle` and `SearchRun` remain documented mutable working aggregates.
- ORM/domain names overlap and the package name `jmoraIs` has unconventional casing.
- Deprecated fail-closed tombstones remain for compatibility.
- Long orchestration methods remain in package issuance, ledger registration,
  authoritative connectors and verification decision logic.
- Connector/service families remain duplicated outside the canonical composition path.
- Replay currently scans whole streams and has no pagination, incremental verified
  snapshot or performance budget.
- Checkpoints and event history reside under the same database-administrator boundary.
- Deferred embeddings code and dependency metadata are inconsistent.
- Coverage is high overall but replay (77%), PubMed (70%), governance adapters (62%)
  and embeddings (0%) deserve targeted attention.

## Operational risks

- No CI evidence or immutable build provenance.
- No deployment or rollback pipeline.
- No backup/restore/PITR proof.
- No health, latency, integrity, capacity or cost monitoring.
- No database growth/replay performance measurements.
- No incident or tamper-response runbook.

## Scientific risks

- Live authoritative integrations were not executed in this audit.
- Benchmark size and diversity do not support statistical performance claims.
- External APIs may change availability, schema, throttling or metadata behavior.
- Guideline authority remains a caller-provided string rather than a governed registry.
- Full-text methodological appraisal is not an automated validated capability.

## Clinical risks

- This is clinical decision-support infrastructure, not validated autonomous care.
- No Patient Context or patient-specific safety validation exists.
- Appraisal inputs are typed but still caller-supplied.
- Reviewer identity is not tied to an institutional identity/credentialing source.
- No real-world clinical validation, inter-rater study or safety monitoring exists.
- Human review is necessary but does not itself establish regulatory safety.

## Release decision

# ALPHA

The platform may be treated as an internal engineering/clinical-governance ALPHA.
It is suitable for controlled development, architecture validation and de-identified
internal evaluation. It is not suitable for external clinical action, patient care,
production deployment or regulatory claims.

The move from `NOT READY` is justified by closure of the prior trust-boundary,
authorization, lifecycle, database immutability, concurrency and replay blockers.
The refusal to classify as BETA is driven by release-artifact irreproducibility,
unexecuted live scientific integrations, narrow benchmark coverage, absent CI/IAM
and weak operational/regulatory readiness.

## Exact requirements for the next release stage

To reach **BETA**, all of the following must be completed and independently audited:

1. Produce a reviewed commit/PR and clean tagged release containing ST-18–ST-21.
2. Make Python 3.12/PostgreSQL 16 tests mandatory in CI with zero PostgreSQL skips.
3. Run the authoritative online benchmark in a controlled CI/manual release job,
   publish its dataset version and acceptance thresholds, and expand its diversity.
4. Introduce a persistent authoritative reviewer identity adapter and test role
   revocation, inactive users and least privilege end-to-end.
5. Update all governing documentation and package declarations to match reality.
6. Add structured, redacted security/audit logging plus integrity-alert handling.
7. Prove application/migration/replay PostgreSQL roles and grants.
8. Demonstrate backup restoration and full cryptographic replay on the restored copy.
9. Establish performance budgets and pass representative ledger/concurrency tests.
10. Document ALPHA intended use, prohibited use, human-review responsibilities and
    the preliminary clinical/regulatory risk register.
