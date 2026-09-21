# JMORAIS-AI Development Playbook

## 1. Status and authority

This is the canonical operational manual for engineering agents, developers, reviewers and architects. It defines how changes are designed, implemented and validated. `AGENTS.md` is the concise entry point; scientific, security and bounded-context documents provide specialized detail. Historical audits and release reports are evidence, not competing architecture authorities.

If documents disagree, apply this order: safety/legal restrictions; `AGENTS.md`; this Playbook; `SCIENTIFIC_EVIDENCE_POLICY.md` and `SECURITY.md`; `ARCHITECTURE.md`; bounded-context documentation; roadmap; historical reports. Stop for architectural review when reconciliation would alter a trust boundary.

## 2. Mission, intended use and maturity

JMORAIS-AI is a provenance-first medical evidence-governance and clinical decision-support platform for qualified professionals. Its mission is to preserve scientific truth, clinical attribution, explainability, auditability and human accountability across evidence, structured clinical context, governed recommendations and draft documents.

Current maturity is `v0.2.0-beta.1`, approved for internal engineering, scientific validation, clinical-governance evaluation and controlled pilots. It is not approved for autonomous clinical decisions, direct patient care, production healthcare deployment, payer authorization or regulatory claims.

Human review is a necessary trust control, never proof of clinical validity by itself. No generated artifact is externally actionable unless a future, separately authorized production policy explicitly permits it. Today all clinical, document, audit-defense and LLM outputs remain non-actionable.

## 3. Canonical bounded contexts

### 3.1 Scientific Core

- **Responsibility:** authoritative retrieval, identifier confirmation, PubMed/Crossref reconciliation, metadata conflict detection, deduplication, provenance, ledger linkage and verification decision.
- **Allowed input:** search/identifier commands and untrusted authoritative-source responses through connector ports.
- **Output:** internal reconciliation results, explicitly untrusted discovery DTOs, and verified issuance inputs for EvidencePackage.
- **Prohibited:** treating regex as verification; allowing consumers to call connectors; exporting internal `EligibleEvidenceResult` as trusted evidence.
- **Trust boundary:** no scientific evidence leaves as trusted except through EvidencePackage issuance.
- **Canonical ports:** `PubMedVerificationPort`, `CrossrefVerificationPort`, connector ports used by `AuthoritativeReconciliationPipeline`, `LedgerHistoryPort`, `PackageCatalogRepository` and `EvidencePackageQueryPort`.

### 3.2 EvidencePackage

- **Responsibility:** immutable, integrity-protected certificate binding verified publication identity, provenance, ledger history, policy and pipeline versions.
- **Allowed input:** reconciled `VERIFIED` evidence with complete provenance and active ledger linkage.
- **Output:** opaque package ID and lifecycle-aware validated `EvidencePackage`.
- **Prohibited:** caller-assigned verification status, forged dictionaries, stale cached validity or missing ledger/provenance.
- **Trust boundary:** validity is recomputed from canonical ledger history; retraction, invalidation, supersession and expiry revoke use without rewriting history.
- **Canonical ports:** `EvidencePackageQueryPort`, `PackageCatalogRepository`, `LedgerHistoryPort`.

### 3.3 Clinical Appraisal

- **Responsibility:** methodological quality, evidence level, recommendation strength, applicability and guideline governance appraisal.
- **Allowed input:** integrity-valid EvidencePackage and attributed appraisal criteria.
- **Output:** immutable appraisal results eligible for GovernedEvidence construction.
- **Prohibited:** raw publications/connectors, invented quality scores, silent guideline validity assumptions.
- **Trust boundary:** incomplete, expired, withdrawn, superseded or critically conflicted appraisals fail closed.
- **Canonical service/ports:** `ClinicalAppraisalService`; package resolution uses canonical `EvidencePackageQueryPort`.

### 3.4 GovernedEvidence

- **Responsibility:** reference-only governed bridge from EvidencePackage/appraisal to clinical consumers, including lifecycle and integrity.
- **Allowed input:** valid package, complete appraisal, provenance and ledger references.
- **Output:** immutable `GovernedEvidence` ID resolved with current lifecycle.
- **Prohibited:** duplicated scientific payload, issuance-time validity caching, raw package consumption by clinical engines.
- **Trust boundary:** only `ACTIVE` GovernedEvidence may be consumed.
- **Canonical ports:** `GovernedEvidenceRepository`, `GovernedEvidenceQueryPort`, `GovernedEvidenceLifecycleEligibilityPort` and lifecycle repository.

### 3.5 Patient Context

- **Responsibility:** sole canonical immutable representation of structured patient context and timeline.
- **Allowed input:** typed, authorized, minimized, de-identified ingestion output.
- **Output:** versioned pseudonymous `PatientContext` and traceable event references.
- **Prohibited:** diagnosis, treatment, interpretation, scientific retrieval, direct identity or anonymous facts.
- **Trust boundary:** context writes occur only through the privacy/ingestion boundary; public direct writes fail closed.
- **Canonical port:** `PatientContextRepository`.

### 3.6 Privacy and Ingestion Boundary

- **Responsibility:** classification, purpose/legal basis, authorization, pseudonymization, de-identification, minimization and access audit.
- **Allowed input:** typed clinical ingestion commands from registered sources.
- **Output:** minimized pseudonymous data eligible for Patient Context persistence.
- **Prohibited:** silent purpose reuse, unsafe free text, reversible identifiers, direct identity in clinical aggregates.
- **Trust boundary:** raw acquisition must pass this boundary before Patient Context exists.
- **Canonical ports:** `ClinicalDataAuthorizationPort`, `PatientIdentityMappingPort`, `PseudonymizationPort`, `DeidentificationPort`, `DataMinimizationPort`, `ClinicalAccessAuditRepository`.

### 3.7 Clinical State

- **Responsibility:** deterministic temporal projection of authorized Patient Context, problem lifecycle, epistemic status and quality flags.
- **Allowed input:** Patient Context only through `PatientContextQueryPort`.
- **Output:** immutable `PatientClinicalState` snapshots and attributable transitions.
- **Prohibited:** identity data, diagnosis/treatment inference, promotion of reported/suspected/inferred facts, silent conflict resolution.
- **Trust boundary:** unresolved conflicts force `REVIEW_REQUIRED`; every new fact creates a new version.
- **Canonical ports:** `PatientContextQueryPort`, `ClinicalStateRepository`, `ClinicalStateAuditPort`, `ClinicalNormalizerPort`.

### 3.8 Clinical Reasoning Input

- **Responsibility:** exclusive reference-only contract for downstream clinical intelligence.
- **Allowed input:** governed references to clinical state, timeline, evidence, guidelines, terminology, provenance, policies and audit.
- **Output:** immutable `ClinicalReasoningInput` with deterministic readiness.
- **Prohibited:** embedded Patient Context, clinical payloads, EvidencePackage payloads, arbitrary dictionaries or unreviewed conflicting input.
- **Trust boundary:** downstream modules accept this object, never raw upstream aggregates.
- **Canonical ports:** `ClinicalReasoningInputRepository`, `ClinicalReasoningInputQueryPort`, `ClinicalReasoningInputAuditPort`.

### 3.9 Clinical Terminology

- **Responsibility:** canonical versioned concepts, code mappings, relationships and UCUM normalization.
- **Allowed input:** licensed, versioned terminology records with provenance.
- **Output:** active concepts, explicit mapping candidates and normalized units.
- **Prohibited:** fabricated codes, guessing ambiguous mappings, using deprecated concepts as current, redistributing unlicensed datasets.
- **Trust boundary:** ambiguity or low confidence produces `REVIEW_REQUIRED`; unknown remains unknown.
- **Canonical ports:** `TerminologyRepository`, `TerminologyQueryPort`, `ConceptMappingPort`, `TerminologyAuditPort`, `UnitNormalizationPort`.

### 3.10 Guideline Recommendation Engine

- **Responsibility:** deterministic guideline applicability, validity, evidence aggregation, conflict detection, ranking and explainability.
- **Allowed input:** ready ClinicalReasoningInput, active GovernedEvidence, active terminology and appraised guideline records.
- **Output:** immutable, non-actionable `GuidelineRecommendationSet`.
- **Prohibited:** raw PubMed/package/context, independent clinical diagnosis or treatment selection, hiding conflicts.
- **Trust boundary:** expiry, withdrawal, supersession, policy mismatch, critical conflict or revoked evidence blocks approval.
- **Canonical ports:** `GuidelineQueryPort`, `RecommendationRepository`, `RecommendationAuditPort`, `GovernedEvidenceLifecyclePort`, `GovernedTerminologyConceptQueryPort`.

### 3.11 Orthopedic Intelligence

- **Responsibility:** structured anatomical, laterality, mechanical, stability, functional, imaging, evidence and guideline correlation.
- **Allowed input:** ready ClinicalReasoningInput plus governed reference ports.
- **Output:** immutable, non-actionable `OrthopedicAssessmentSet`.
- **Prohibited:** diagnosis, surgical indication, treatment, imaging reinterpretation, unsupported severity or raw clinical/scientific input.
- **Trust boundary:** suspected facts remain suspected; discordance and unsupported severity require review.
- **Canonical ports:** `GovernedOrthopedicStateQueryPort`, governed evidence/lifecycle/guideline/terminology query ports, `OrthopedicAssessmentRepository`, `OrthopedicAuditPort`.

### 3.12 Medical Document Engine

- **Responsibility:** deterministic, source-bound composition of governed medical drafts and traceability manifests.
- **Allowed input:** ready ClinicalReasoningInput and governed clinical, terminology, evidence, guideline, orthopedic and canonical citation references.
- **Output:** immutable `MedicalDocumentVersion` in structured JSON, text or Markdown.
- **Prohibited:** filler, invented facts/citations, raw inputs, independent Vancouver construction, external identity rendering or autonomous authorization.
- **Trust boundary:** validation blocks unsupported statements, invalid citations, identity leakage, hidden conflict and missing provenance.
- **Canonical ports:** governed document query ports, `CanonicalCitationQueryPort`, `MedicalDocumentRepository`, `MedicalDocumentQueryPort`, `DocumentTemplateRepository`, `DocumentAuditPort`.

### 3.13 Audit Defense

- **Responsibility:** deterministic aggregation of clinical, scientific and guideline support, counterarguments, conflicts and limitations.
- **Allowed input:** ready ClinicalReasoningInput and governed clinical/evidence/guideline/orthopedic/terminology references.
- **Output:** immutable, non-actionable `DefensePackage`.
- **Prohibited:** payer-specific decisions, free audit prose, fabricated indication, evidence or citation, autonomous authorization.
- **Trust boundary:** critical conflict or insufficient support remains `REVIEW_REQUIRED` and blocks approval.
- **Canonical ports:** governed audit query ports, `AuditDefenseRepository`, `AuditDefenseQueryPort`, `AuditDefenseEventPort`.

### 3.14 LLM Gateway

- **Responsibility:** exclusive provider communication, DTO allowlisting, prompt integrity, retries, output classification, token/cost accounting and privacy-preserving audit.
- **Allowed input:** validated `MedicalDocument`, `AuditDefense`, `OrthopedicAssessment`, `ClinicalReasoningInput` and approved `CanonicalStructuredDTO`.
- **Output:** classified, always non-actionable `LLMResponse`.
- **Prohibited:** provider calls elsewhere, raw Patient Context/EvidencePackage/database objects, identity, secrets, arbitrary text, embeddings or reasoning policy.
- **Trust boundary:** prompt hash, policy and mandatory human review are checked before every invocation; secrets are blocked.
- **Canonical ports:** `LLMGateway`, `PromptRepository`, `PromptAuditRepository`, `InvocationRepository`, `ProviderAdapter`.

## 4. Mandatory trust paths

No supported flow may skip a node:

```text
Scientific source
→ authoritative verification and reconciliation
→ provenance
→ canonical append-only Scientific Ledger
→ integrity-valid EvidencePackage
```

```text
Typed clinical acquisition
→ privacy/authorization/purpose/de-identification/minimization boundary
→ Patient Context
→ Patient Clinical State
→ Clinical Reasoning Input
→ governed downstream module
→ authorized human review
```

```text
EvidencePackage
→ Clinical Appraisal
→ active GovernedEvidence
→ guideline/clinical/orthopedic/document/audit consumers
```

```text
Allowlisted canonical DTO
→ LLM Gateway policy and prompt-integrity gate
→ replaceable governed ProviderAdapter
→ classified non-actionable draft
→ human review
```

Architecture tests must make direct connector, package, clinical-state, governance, reviewer and provider bypasses mechanically difficult.

## 5. Permanent global invariants

1. Fail closed on absent, invalid, ambiguous, expired, revoked, conflicting or unauthorized data.
2. Domain entities and public artifacts are immutable frozen values; documented internal working aggregates are the only exceptions.
3. Historical, governance and audit state is append-only. Corrections, invalidation, retraction and supersession append new facts.
4. Every aggregate and policy decision is versioned; every later version references its predecessor.
5. Provenance, source identity and timestamps are mandatory. Anonymous evidence or clinical facts are prohibited.
6. Format validity is never authoritative existence verification.
7. No scientific reference, identifier, code, diagnosis, procedure, indication or patient fact may be fabricated.
8. Raw connector results never cross into consumers; arbitrary dictionaries never cross trust boundaries.
9. No destructive historical mutation, silent conflict resolution or silent metadata completion.
10. Confidence never overrides verification, authorization, provenance, applicability or conflict.
11. No autonomous diagnosis, treatment, prescribing, surgery indication, coverage decision or clinical action.
12. Authorized human review is required before any future actionability; current outputs remain non-actionable even after review.
13. Domain/application layers own policy and ports. Infrastructure implements adapters and may not define business eligibility.
14. New parallel domain concepts, ports or business rules require explicit architectural review.

## 6. Scientific rules

- Validate PMID/DOI syntax separately from authoritative existence.
- PMID confirmation uses NCBI/PubMed; DOI confirmation uses Crossref when applicable.
- PubMed is primary when PMID exists; reconcile title, authors, journal, year and identifiers with Crossref.
- Preserve every source payload, discrepancy, retrieval timestamp and merge decision.
- Deduplicate in order: DOI, PMID, PMCID, normalized title, author/year/journal. Never silently discard conflicts.
- Verification statuses are canonical: `VERIFIED`, `PARTIALLY_VERIFIED`, `CONFLICTING_METADATA`, `NOT_VERIFIED`.
- Support directions reuse the scientific enum: `SUPPORTING`, `OPPOSING`, `NEUTRAL`, `INCONCLUSIVE`.
- Only `VERIFIED`, provenance-complete, ledger-linked evidence may issue an EvidencePackage.
- Package validity is live and certificate-like; retraction, invalidation, supersession and expiry must revoke consumption.
- The Scientific Ledger is immutable, hash chained, replayable and complete against independent checkpoints.
- Vancouver is fail-closed and generated only by the canonical Scientific Core formatter from persisted verified metadata. LLMs and downstream modules never author bibliographic truth.
- Release benchmark datasets are real, versioned and governed. Minimum composition and metric thresholds in `SCIENTIFIC_BENCHMARK_ACCEPTANCE.md` may not be weakened to pass release gates.

## 7. Clinical-data and governance rules

- Persist only canonical pseudonymous patient IDs; isolate direct identity behind `PatientIdentityMappingPort`.
- Every ingestion has actor, organization, source, purpose of use, legal basis, authorization decision and policy version.
- Apply deterministic de-identification and purpose-based minimization before persistence.
- Unsafe free text is `REVIEW_REQUIRED`, never automatically accepted.
- Preserve epistemic status: confirmed, reported, observed, suspected, inferred or unknown. Never promote it implicitly.
- New information produces a new context/state version. Historical snapshots remain unchanged.
- Data-quality flags and conflicts are explicit. `REVIEW_REQUIRED` means downstream reasoning/action is blocked until governed adjudication.
- Audit metadata must not copy unnecessary sensitive clinical payloads.

## 8. Terminology rules

- Use the terminology bounded context for all internal clinical concepts.
- Record code system, code, release/version, status, effective/retirement dates, source, license and provenance.
- One-to-many, many-to-one and ambiguous mappings retain all candidates. Never guess a winner.
- Deprecated, superseded and retired concepts remain reconstructable and cannot silently act as active concepts.
- Use UCUM for governed unit normalization and preserve original value/unit plus conversion provenance.
- Do not bundle or redistribute restricted terminology content without an approved license.

## 9. Guideline rules

- Recommendations require methodological appraisal and governed evidence.
- Recheck publication/effective/expiration/withdrawal/supersession status for every use.
- Applicability uses only available structured context; absent population factors require review, not inference.
- Recommendation strength and evidence certainty are distinct concepts.
- Supporting, opposing, neutral and inconclusive evidence remain separate.
- Preserve direction, organization, version and strength conflicts. Critical positive-versus-negative guidance blocks approval.
- Reviewer approval delegates to canonical `AuthorizedRecommendationReviewService`; never create a parallel review system.

## 10. Orthopedic rules

- Produce structured assessment and correlation only.
- Use governed anatomical, laterality, finding, examination and unit concepts.
- Do not infer diagnosis, reinterpret imaging, indicate surgery or select treatment.
- Unsupported severity becomes unknown/review-required.
- Preserve imaging/clinical discordance and laterality conflicts.
- Evidence and guideline correlation reference governed artifacts and current lifecycle.
- Human review does not enable clinical action under the current policy.

## 11. Medical-document rules

- Every factual statement is source-bound and retains epistemic status.
- Missing information uses explicit markers; never generate plausible filler.
- Scientific sections reference active GovernedEvidence and canonical verified Vancouver output.
- Templates are immutable, versioned and declare section/source policy.
- The validation gate blocks unsupported claims, invalid citations, privacy leakage, hidden conflicts and missing provenance.
- Corrections append a new document version and retain reviewer, justification and predecessor.
- Every rendered section has a traceability-manifest entry.
- Procedure-justification and audit-support documents remain drafts without authorization effect.

## 12. Audit-defense rules

- Accept governed references only; never ingest payer prose or arbitrary free text as trusted claims.
- Aggregate all evidence directions and expose opposition.
- Counterarguments are deterministic representations of source-backed opposition or guideline conflict, not invented narrative.
- Missing, stale, conflicted and upstream-limited information remains explicit.
- Never fabricate diagnosis, procedure, indication, evidence or citation.
- No payer authorization/coverage decision is implemented.
- Critical limitations block approval; canonical human review remains mandatory.

## 13. LLM rules

- Only `jmoraIs.llm_gateway` may contact a model provider. Static architecture tests enforce this.
- Inputs use an exact canonical DTO allowlist; ORM/database/infrastructure objects, arbitrary text and dictionaries fail closed.
- Prompt templates are immutable, versioned, hash protected, policy-bound and input-schema-bound.
- Provider/model enablement, pricing policy, seed, temperature and output limit are explicit.
- Direct identity, credentials, API keys, bearer tokens and passwords are prohibited.
- Operational audit stores hashes and metrics, not prompt payload, DTO contents or model output.
- Every response is `DRAFT`, `REVIEW_REQUIRED`, `BLOCKED` or `APPROVED_FOR_REVIEW`; none is externally actionable.
- Adapters remain replaceable behind `ProviderAdapter`; provider-specific SDKs/transports stay in infrastructure.

## 14. Database and integrity rules

- Canonical runtime database is PostgreSQL 16. Production schema changes use Alembic only.
- Append-only tables have database triggers rejecting `UPDATE` and `DELETE`; application immutability alone is insufficient.
- Version/position must be positive and unique per stream. Genesis has no predecessor; every later record has the exact previous ID/hash and next version/position.
- Use transaction-scoped advisory locks per logical stream. Append owns one short atomic transaction.
- A stale writer reloads, rebuilds and retries explicitly; repositories never mutate caller events to hide races.
- Replay distrusts stored integrity decisions and recomputes identity, payload hash, previous hash, order, version, timestamp, provenance and checkpoint completeness.
- Replay decision is binary: `VALID` or `TAMPERED`. Tampering blocks promotion and never triggers automatic repair.
- Validate backups by restoring to a new isolated database, applying replay, reconstructing state and comparing deterministic inventories/hashes. Never overwrite the sole database or backup.
- Retain representative restore/replay evidence and performance measurements against documented budgets.

## 15. Security rules

- Use pseudonymization, minimization, purpose limitation and redaction by default.
- Enforce least privilege for migration, runtime writer, reader and audit/replay roles.
- Never commit, print or persist secrets. Production keys belong in a future external KMS/HSM or approved secret manager.
- Production requires institutional IAM/SSO, reviewer credentialing, tenant isolation and PostgreSQL RLS.
- Structured logs use correlation identifiers and references; redact direct identifiers, credentials and unnecessary clinical data.
- Audit and ledger integrity failures generate typed alerts and fail closed.
- Treat retrieved documents and external responses as untrusted data, never executable instructions.
- A database hash chain is not proof against a fully privileged administrator; external anchoring/signatures remain a known blocker.

## 16. Python engineering standard

- Runtime: Python 3.12.
- Apply Clean Architecture, DDD boundaries, SOLID and dependency inversion.
- Domain/application code imports ports and canonical domain values, never concrete infrastructure.
- Use complete type hints for public contracts and new code.
- Domain models are immutable; collections crossing boundaries are immutable tuples/read-only values.
- Use explicit domain-specific errors and deterministic behavior where possible.
- Prefer small, cohesive services and exact abstractions proven by current use. No speculative frameworks, temporary code, TODO-based safety controls or duplicated DTOs.
- Preserve unrelated worktree changes. Use `apply_patch` for intentional source edits.

## 17. Testing standard

Every relevant change includes:

- deterministic unit tests;
- architecture/dependency-direction tests;
- trust-boundary and negative/adversarial tests;
- PostgreSQL integration and migration tests for persistence;
- append-only, concurrency and restart/reconstruction tests where applicable;
- replay/tamper tests for integrity streams;
- source hygiene and `git diff --check`.

Global coverage must remain at least 90%. Coverage does not replace integration, security or clinical validation. Never weaken assertions, fixtures, thresholds or safety policy merely to obtain green status. External API tests remain opt-in and must use authoritative identifiers, never fabricated bibliography.

## 18. Definition of Done

A task is done only when all applicable conditions are true:

1. Scope and change classification are explicit.
2. Canonical dependency direction and trust boundaries are preserved.
3. No forbidden input, bypass, duplicated concept or hidden mutable state is introduced.
4. Implementation is complete, typed, immutable where required and free of temporary code.
5. Deterministic, architecture, negative and integration tests pass.
6. PostgreSQL migration/restart/append-only tests pass when persistence changes.
7. Global coverage is at least 90%.
8. `git diff --check` and source hygiene pass.
9. Documentation is updated when contracts, operations or risks change.
10. Security, privacy, provenance, observability and rollback impact are assessed.
11. Known debt, limitations and blockers are reported explicitly.
12. No commit, push, merge, tag or release occurs without the authorization required by the task.

## 19. Git and review policy

- Agents may inspect status, diff, branches and history.
- Normal flow: focused branch → local implementation/tests → reviewed diff → pull request → CI → independent review → authorized merge.
- Do not merge, force-push, rewrite history, delete branches, tag releases or push unless the user explicitly authorizes that exact action.
- Never use destructive reset/checkout to discard an existing worktree.
- Architecture changes require an approved decision before implementation and dedicated architecture/security review.
- Releases use immutable reviewed commits; retain test, migration, benchmark and replay evidence associated with the released commit.

## 20. Change classification and review depth

| Type | Definition | Required review |
|---|---|---|
| `FEATURE` | New in-scope behavior within existing boundaries | Domain owner; security/privacy and clinical review when affected; full applicable DoD. |
| `BUGFIX` | Restores documented behavior without changing the contract | Root-cause and regression review; focused negative test; broader review if trust behavior changes. |
| `REFACTOR` | Changes structure without intended behavior change | Architecture/dependency tests, equivalence/regression evidence and owner review. |
| `ARCHITECTURE CHANGE` | Alters a trust boundary, canonical owner/port, dependency direction, persistence invariant, policy or public contract | Stop before implementation. Produce impact/risk analysis and obtain explicit architecture review/authorization; require architecture, security, migration and affected clinical/scientific reviews. |

When uncertain, classify upward. A “small” edit that changes who may trust or consume an artifact is an architecture change.

## 21. Reusable future-task template

```text
TASK:
[objective and change classification]

SCOPE:
[bounded context and files/contracts in scope]

REQUIREMENTS:
- [observable requirement]
- [trust/security requirement]

DO NOT:
- [out-of-scope behavior]
- bypass canonical trust paths
- commit, push or merge unless explicitly authorized

VALIDATION:
- python3 -m pytest -q
- PostgreSQL tests if persistence is affected
- coverage >= 90%
- git diff --check
- source hygiene

RETURN:
- files created/modified
- architecture and behavior
- tests and measured results
- remaining blockers
```

Normal tasks should reference this Playbook instead of repeating its permanent rules. Add task-specific constraints only.

## 22. Unresolved blocker register

These blockers remain open and must not be reported as resolved without objective evidence and approval:

| Blocker | Required outcome |
|---|---|
| Direct identity vault | Persistent, separately authorized mapping service with access audit and emergency controls. |
| External KMS/HSM | Managed key lifecycle, rotation, access policy and recovery. |
| IAM/SSO | Institutional authentication, reviewer credentialing, revocation and service identity. |
| PostgreSQL RLS | Tested tenant/purpose isolation under least-privilege roles. |
| Multi-tenant isolation | End-to-end isolation across database, caches, logs, jobs and artifacts. |
| LGPD/legal validation | Data inventory, lawful basis, DPIA, retention, subject workflows and vendor governance. |
| Terminology licensing | Approved distribution licenses, release verification and institutional mapping governance. |
| Institutional clinical validation | Prospective protocols, inter-rater assessment, safety case and accountable medical governance. |
| Model/provider governance | Approved providers/models, DPA/privacy/ZDR, regional routing, evals, budgets and change control. |
| External monitoring | Production telemetry, integrity alerts, SLOs, incident response and independent delivery. |
| Clinical production authorization | Regulatory/intended-use decision, deployment controls and explicit accountable authorization. |

## 23. Phase 3 preparation — not implementation authority

Future tracks are authenticated API, web application, IAM/SSO, multi-tenancy, observability, FHIR/HL7 interoperability, production deployment, model evaluations, clinical validation and regulatory readiness. Each begins with architecture/security/privacy review, threat model, acceptance criteria and rollback plan. Listing a track here does not authorize implementation, external integration, patient use or production deployment.

## 24. Operating checklist for agents and reviewers

Before work: read `AGENTS.md` and this Playbook; identify the bounded context, canonical ports, change classification, trust path, prohibited dependencies and blockers. Inspect the current branch/worktree without overwriting unrelated changes.

During work: keep the change minimal; use canonical types/ports; preserve immutability, provenance and append-only behavior; communicate new risks immediately; stop for architecture review if the boundary changes.

Before handoff: execute the applicable DoD, report exact commands/results and skips, list all files, state unresolved blockers, and distinguish technical approval from clinical, production or regulatory authorization.
