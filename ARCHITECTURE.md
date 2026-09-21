# JMORAIS AI Architecture v3

RC2 performance and scalability evidence is isolated under `evaluation/performance` and documented in `docs/PERFORMANCE_ENGINEERING.md`, `docs/CAPACITY_MODEL.md`, and `docs/SCALABILITY.md`. Benchmark code may orchestrate production services but production bounded contexts never depend on benchmark code. Capacity optimization cannot weaken trust boundaries.

The production HTTP/network/observability boundary is an infrastructure adapter outside all medical and scientific bounded contexts. It enforces transport, proxy, host and resource admission before the internal API; PostgreSQL RLS and canonical authorization remain independent downstream controls. Offline global replay is never injected into HTTP handlers. Operational details and STRIDE analysis are in `docs/RUNTIME_SECURITY.md` and `docs/THREAT_MODEL.md`.

## Offline global replay boundary

Global cryptographic verification is deployment infrastructure, not a bounded
context or HTTP capability. `OfflineReplayVerifier` orchestrates the canonical
engine through a separate KMS credential, dedicated one-connection pool and
read-only PostgreSQL verifier role. Privileged resources are disposed before the
tenant-scoped `NOBYPASSRLS` API runtime serves traffic.

Audit Defense owns its Human Review governance projection. Human Review depends only on `UpstreamReviewGovernancePort`; a generic router dispatches by artifact type without leaking Audit Defense persistence into the review application.

## Audit Defense exact persisted reference

Audit Defense owns `PersistedDefensePackageReference` issuance and exact resolution. Its metadata-only PostgreSQL record is append-only and tenant-isolated. `AuditDefenseQueryPort.get_exact()` validates package identity/version, tenant, policy, integrity, predecessor continuity and Stage-11 traceability. Gateway remains independent of Audit Defense persistence.

LLM operational traceability propagates an opaque correlation ID from the authenticated
`TenantContext` through the canonical Gateway into append-only invocation and audit
history. Provider adapters have no authority over correlation, and PostgreSQL RLS
isolates correlation queries independently of request identity.

Canonical LLM invocation history additionally persists output classification and the
trusted request temperature/seed. Invocation status is operational execution state and
is never treated as a substitute for output classification.

## Phase 2 — Patient Context boundary

### Guideline Recommendation Engine (MIP-06)

`jmoraIs.guideline_engine` transforms only ready ClinicalReasoningInput plus currently valid governed evidence, terminology and guideline appraisal records into non-actionable, explainable recommendation sets. Applicability and ranking are deterministic and versioned; critical conflicts fail closed. External actionability requires the existing authorized reviewer-governance boundary.

Governed guideline inputs are persisted as immutable shared-global source records behind the existing `GuidelineQueryPort`. PostgreSQL preserves source/appraisal/provenance history and rejects destructive mutation; MIP-06 remains infrastructure-independent. See `docs/GUIDELINE_SOURCE_PERSISTENCE.md`.

### Clinical Terminology & Coding Layer (MIP-05)

`jmoraIs.terminology` owns canonical clinical concepts, code-system versions, deterministic mappings, orthopedic vocabulary categories and UCUM conversions. Consumers use its query and mapping ports; ambiguous and unknown terms fail closed without invented codes. Licensed terminology datasets are external governed inputs and are not embedded in this repository.

Canonical concept truth is separate from append-only mapping-governance decisions.
Audit Defense reconstructs governed terminology after restart from both canonical
PostgreSQL histories and never infers mapping confidence from concept lifecycle.

### Clinical Reasoning Input contract (MIP-04)

`jmoraIs.reasoning_input` is the exclusive reference-only input boundary for future intelligent clinical modules. It binds governed references to an immutable versioned contract and calculates readiness fail-closed. It does not import or embed Patient Context, Clinical State, EvidencePackage or GovernedEvidence entities. Future engines must consume this contract through `ClinicalReasoningInputQueryPort` and may not accept raw upstream objects.

### Derived Patient Clinical State (MIP-03)

`jmoraIs.clinical_state` derives immutable, temporal snapshots exclusively through `PatientContextQueryPort`. It references rather than duplicates source payloads, preserves epistemic uncertainty, represents problem transitions as attributable append-only history, and fails to `REVIEW_REQUIRED` on unresolved quality conflicts. Its repositories and audit ports are owned by the bounded context; no scientific connector or decision engine is reachable from this dependency direction.

MIP-07 consumes a deterministic tenant-scoped `GovernedOrthopedicStateView` reconstructed after restart from RLS-protected Clinical State and canonical terminology. See `docs/GOVERNED_ORTHOPEDIC_STATE.md`.

MIP-08 resolves tenant-scoped `DocumentFactReference` values through deterministic restart-safe reconstruction of persisted Clinical State. Epistemic status, quality conflicts, review status and provenance remain unchanged. See `docs/GOVERNED_DOCUMENT_CLINICAL_STATE.md`.

MIP-08 terminology references are reconstructed without cache from the canonical shared PostgreSQL terminology repository through `GovernedDocumentTerminologyPort`; inactive concepts remain review-gated.

The `jmoraIs.patient_context` bounded context is the sole canonical representation of patient context. It is independent from the frozen Scientific Core and governed clinical path, owns its repository port, exposes immutable versioned aggregates, and performs no medical reasoning. Future Phase 2 consumers must resolve patient context through this boundary rather than introduce parallel patient DTOs.

MIP-02 adds the exclusive clinical ingestion trust path: typed input → source validation → scoped authorization/legal basis → purpose and classification → deterministic de-identification → minimization → provenance → append-only Patient Context. Direct identifiers are isolated behind `PatientIdentityMappingPort`; clinical aggregates contain only HMAC-derived pseudonymous identifiers. Raw free text requiring review is blocked, and metadata-only access audit is append-only.

## Validated trust path (ST-22)

Authoritative sources → canonical verification/reconciliation → append-only PostgreSQL ledger → EvidencePackage → appraisal/governance → authorized human review. Consumers cannot bypass package integrity, governance or review. Cryptographic replay validates stream history independently; reviewer identity persistence remains an adapter behind its authorization port. CI, benchmark, monitoring and backup/replay are operational adapters and do not reverse domain dependencies.

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

The canonical application boundary is
`jmoraIs.application.AuthoritativeReconciliationPipeline`. Consumers must use
this use case and must not call PubMed, Crossref, SciELO, or low-level
verification helpers directly. Its result separates all reconciled records from
the subset eligible for evidence use. A record is eligible only when its
authoritative checks are confirmed, reconciliation is `MATCHED`, the decision
was made under policy `ST-02`, and it is linked to the originating `SearchRun`.

Canonical execution order:

Search/identifier input
-> SearchRun
-> PubMed primary retrieval
-> identifier extraction and DOI/PMID association
-> Crossref DOI enrichment when applicable
-> field-level metadata reconciliation
-> provenance-preserving deduplication
-> final verification decision
-> eligible evidence result

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

### 8.1 Evidence Package trust boundary

`ScientificEvidencePackagePort` is the sole public boundary for evidence leaving
the Scientific Core. It issues and resolves immutable, integrity-hashed
`EvidencePackage` records only after authoritative verification, provenance,
an active append-only ledger relationship, and ledger-chain integrity have all
been established. External consumers must use the opaque `package_id`; a
dictionary or caller-assigned `verification_status` is never trusted evidence.

Expired packages are denied by default. Use for revalidation requires an
explicit expiration policy and does not silently renew or mutate the package.

Search and discovery may leave the core only through `ScientificDiscoveryResult`,
which is explicitly marked untrusted and contains no `verification_status` or
eligible-evidence collection. The reconciliation aggregate remains internal.
Trusted issuance is package-only. Consumer modules accept opaque package IDs and
resolve them through the package query port; caller-provided dictionaries,
status strings, articles, and internal pipeline results are rejected.

Evidence Package validity is certificate-like and computed on every query by
replaying the associated append-only ledger up to the evaluation time. Packages
are `ACTIVE`, `SUPERSEDED`, `RETRACTED`, `INVALIDATED`, or `EXPIRED` without
mutating the original package. Retraction, invalidation, correction, and
supersession events revoke affected historical packages automatically; an
`as_of` query preserves temporal reconstruction. Consumers must resolve package
IDs for each use and must not cache a prior validity decision.

Package persistence is accessed through the application-owned
`PackageCatalogRepository` port. The port stores immutable package records,
ledger associations, and version records using append-only operations. It does
not persist a duplicate lifecycle state. In production,
`PostgreSQLCanonicalLedger` appends claims, fragments, supports, and events to
the canonical PostgreSQL event stream. Every lifecycle decision is reconstructed
exclusively by replaying that stream, including after restart. Both the in-memory
reference adapter and PostgreSQL catalog implement the application-owned port;
the application layer does not import or instantiate infrastructure adapters.

Final Vancouver rendering is fail-closed and available only through
`StrictVancouverFormatter` with an Evidence Package resolved by that boundary.
The formatter consumes structured verified metadata, records its formatter
version, and rejects free-form or model-generated citation text. Publication
strategies are explicit for journal articles, electronic articles, guidelines,
books, and book chapters; missing mandatory fields are never synthesized.

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
## MIP-07 Orthopedic Intelligence

`ClinicalReasoningInput → governed state/evidence/terminology/guideline ports → immutable OrthopedicAssessmentSet → canonical human review`. The bounded context is reference-only, append-only, fail-closed, and cannot access raw Patient Context, raw scientific sources, connectors, or infrastructure directly.

## MIP-08 Medical Document Engine

`ClinicalReasoningInput → governed reference ports → versioned deterministic template → validation gate → immutable MedicalDocumentVersion → canonical human review`. Documents contain attributed facts and references, never raw upstream payloads. Vancouver text is accepted only as a canonical verified Scientific Core representation. Corrections, review and audit are append-only; external validity remains disabled.

## MIP-09 Audit Defense AI

`ClinicalReasoningInput → governed clinical/evidence/guideline/orthopedic/terminology ports → deterministic aggregation → immutable DefensePackage → canonical human review`. Arguments and counterarguments are source-bound structures, not generated medical narratives. Conflicts and limitations fail closed; payer decisions and external actionability are prohibited.

Audit Defense clinical facts are reconstructed after restart through `PostgreSQLGovernedAuditClinicalStateAdapter`, a tenant-scoped read projection over canonical `PatientClinicalState` persistence. The projection preserves epistemic state, provenance, quality flags and review state without duplicating clinical truth or adding clinical inference. PostgreSQL RLS remains the isolation authority.

Audit Defense scientific support is resolved through `CanonicalGovernedAuditEvidenceAdapter`, which composes canonical persisted GovernedEvidence, appraisal and lifecycle services. It returns no duplicate scientific model and fails closed unless current package, integrity, appraisal linkage, provenance, ledger linkage and lifecycle are valid.

Audit Defense guideline support is resolved through `PostgreSQLGovernedAuditGuidelineAdapter`, which reconstructs tenant-scoped recommendation sets and validates their canonical reasoning-input, governed source, appraisal, terminology, policy, provenance and review ancestry after restart. Canonical conflicts and recommendation semantics remain unchanged.

Stage 11 and Stage 12 are connected by a workflow-only, exact-version reference.
`AuditDefenseTraceabilityService` appends a `DefensePackage` version containing a
`MedicalDocumentVersionReference` issued from canonical persisted Medical
Document history under RLS. No document content enters Audit Defense reasoning,
and the Medical Document bounded context remains authoritative for document
identity and integrity. See `docs/STAGE11_STAGE12_TRACEABILITY.md`.

## MIP-10 Canonical LLM Gateway

`Canonical DTO → immutable hash-verified prompt → policy gate → provider adapter → classified non-actionable response → hash-only audit`. `jmoraIs.llm_gateway` is the exclusive model-provider boundary. No other bounded context may import provider SDKs or call model endpoints. Prompt payloads and outputs are never written to operational audit history.

The authenticated `TenantContext` is projected into an immutable, tenant-scoped `LLMInvocationContext` and persisted append-only before provider invocation. PostgreSQL RLS and integrity verification provide restart-safe request/correlation/principal/purpose/policy traceability without clinical payloads. Invocation and prompt-audit repositories fail closed on broken request, correlation, or policy linkage.

The persisted review path adds an owner-issued `PersistedGatewayInput`: the owning bounded context rereads an exact version under RLS and atomically attests its canonical DTO plus `UpstreamArtifactReference`. The Gateway verifies this shared contract without importing owner repositories and persists only the upstream reference as operational traceability.

The binding itself is also a canonical metadata-only trust artifact. Its repository
persists the original attestation, opaque managed-key reference, DTO hash and exact
upstream identity under forced RLS and append-only constraints. Invocations reference
its canonical ID. Restart verification reprojects the DTO from the exact owner version,
recomputes the hash and checks the original signature; the trust record participates
in global cryptographic replay.

Each PersistedGatewayInput record is a single-record cryptographic stream with the
tenant-qualified identity `tenant_id|persisted_gateway_input_id`. PostgreSQL appends
its independent completeness checkpoint atomically with the trust row. Global replay
enumerates checkpoint expectations and surviving rows, so deletion of the only row,
missing checkpoints and head divergence fail closed instead of disappearing from
discovery. No historical checkpoint is synthesized for legacy rows.

For an Audit Defense upstream, issuance and reconstruction remain owner-side.
`AuditDefenseGatewayInputResolver` validates the exact final linked
`DefensePackage`, then delegates its Stage-11 reference to the canonical Medical
Document trace adapter. The generic persisted-input service verifies DTO hash and
original attestation; the Gateway gains no Audit Defense repository dependency.

The canonical forward Stage-13 contract is likewise owner-controlled:
`issue_from_package(DefensePackage)` accepts the typed final persisted handoff and
performs a second exact repository equality check. Artifact identity/version are
derived from that verified package. The scalar issuer is legacy-only; validation
adapters may not use it for controlled-pilot evidence.

`jmoraIs.governed_llm_draft` is the separate post-Gateway trust boundary for reviewable content. It validates persisted invocation, context, upstream reference, classification, review policy and the independent exact-content hash before storing an immutable, versioned and tenant-scoped draft. The Gateway remains an operational boundary and never stores reviewable text.

Draft authority is lifecycle-aware: issuance and `ACTIVE` genesis are atomic, while `SUPERSEDED` and `INVALIDATED` append hash-linked tenant events. Consumers query the lifecycle port after restart and never infer status from the latest draft row.
# Clinical Appraisal persistence

Canonical Clinical Appraisal history is now an immutable, append-only shared scientific-governance artifact. Application code depends on appraisal repository/query ports; PostgreSQL persistence is an infrastructure adapter. New GovernedEvidence compositions resolve a persisted appraisal identifier instead of relying on process-local appraisal state. See `docs/CLINICAL_APPRAISAL_PERSISTENCE.md`.
# Canonical scientific citation history

Verified bibliographic metadata and the exact `VancouverReference` are persisted as immutable `ScientificCitationRecord` versions inside the Scientific Core. Query is restart-safe and lifecycle-aware through the existing EvidencePackage/ledger boundary. The legacy `citations` table is non-authoritative and is not a canonical source. See `docs/SCIENTIFIC_CITATION_PERSISTENCE.md`.

The Medical Document bounded context consumes this history only through `CanonicalCitationQueryPort`. `CanonicalDocumentCitationAdapter` is a reference-only projection over `ScientificCitationQueryPort`; Vancouver formatting and scientific validity remain owned by the Scientific Core.
# Stage 14 — LLM Human Review

`jmoraIs.llm_human_review` is the governed human-review boundary after `GovernedLLMDraft`. It reuses canonical IAM, session/JTI, tenancy, reviewer governance and PostgreSQL RLS. Its immutable hash-linked decisions never grant external actionability.

The continuous security composition is OIDC → persisted identity link → session/JTI → canonical tenant resolution → persisted reviewer → managed attestation → review service. Decision history and metadata-only security history are separate append-only streams; no draft content is duplicated.
## Stage-13/14 cryptographic replay boundary

`PostgreSQLCryptographicReplayEngine` is the infrastructure-only, read-only
integrity verifier for release acceptance. In addition to the Scientific Ledger,
EvidencePackage, GovernedEvidence, and governed clinical streams, its mandatory
registry includes GovernedLLMDraft lifecycle, LLM human-review decisions, and
human-review security audit. Each tenant-scoped stream is independently replayed
from PostgreSQL, hash-recomputed, reference-checked, and compared with the shared
append-only completeness checkpoint stream. Any omitted, unverifiable, incomplete,
or altered mandatory stream makes the global decision `TAMPERED`.
## Authorized Clinical Ingestion — Stage 1

The Patient Context bounded context owns an immutable metadata-only
`AuthorizedClinicalIngestionRecord`. `ClinicalIngestionService` atomically commits
the minimized PatientContext version, this Stage-1 governance record and successful
privacy audit events through an application-owned repository port. The record
references rather than duplicates PatientContext. Stage 1 is reread by ingestion
record ID; Stage 2 is reread by its exact context ID/version. PostgreSQL is the
atomicity boundary, with tenant RLS, append-only enforcement and integrity-hash
validation.
## Patient Context exact-reference boundary

The Patient Context owner issues an immutable, metadata-only
`PersistedPatientContextReference` only after equality with canonical PostgreSQL
state is proven. Exact reread validates persisted reference authenticity, exact
version and subject linkage, tenant, policy, context integrity, authorized-ingestion
lineage and predecessor continuity. The reference contains no clinical payload and
cannot be reconstructed from caller scalars, `latest()` or a history scan. This is
the sole Patient Context trust input prepared for future FHIR incremental updates;
FHIR does not become a source of truth.
## FHIR R4 interoperability boundary

`jmoraIs.fhir` is a one-way Clinical Applications adapter for FHIR R4 `4.0.1`.
It owns parsing, bounded structural validation, Bundle-local reference resolution,
deterministic mapping and provenance only. It invokes the canonical
`ClinicalIngestionService`; Patient Context remains the sole clinical source of
truth and sole issuer of exact persisted context references. Incremental updates
consume only `PersistedPatientContextReference`, and idempotency is reconstructed
from canonical authorized-ingestion and exact-reference metadata. Frozen bounded
contexts never import FHIR types, and no raw FHIR payload is persisted.

## SMART on FHIR authentication boundary

`jmoraIs.smart_fhir` validates the SMART/OIDC protocol envelope before any FHIR
handoff. It parses deterministic discovery and JWKS documents, enforces signed JWT
claims and PKCE S256, and returns reference-only launch/scope metadata. It neither
authorizes clinical operations nor creates PatientContext. External identity-to-
tenant linkage remains owned by canonical IAM; metadata-only authentication audit
reuses the existing append-only identity-security persistence.

## Clinical State exact-reference boundary

Clinical State owns `PersistedClinicalStateReference` and
`PersistedClinicalStateTimelineReference`. Exact state resolution verifies an
owner-issued persisted reference; exact timeline resolution follows only its
persisted ordered member references. Neither path uses `latest()`, `at()` or a
history scan to establish trust. These metadata-only, tenant-scoped records prepare
the read-only S003 viewers without changing Clinical State semantics or payloads.

## Governed Evidence exact-reference boundary

Governed Evidence owns `PersistedGovernedEvidenceReference`. Owner issuance binds
the exact persisted stream version to its EvidencePackage, eligible appraisal,
policy, provenance and current `ACTIVE` lifecycle event. S003 consumers may resolve
it only through `get_exact(reference)`. The metadata-only stream is RLS-protected,
append-only and completeness-checkpointed for Offline Replay; scalar evidence IDs
remain compatibility identifiers, not workspace trust inputs.
## Exact guideline-set lineage

The Guideline Engine owns opaque, tenant-scoped exact references to persisted `GuidelineRecommendationSet` versions. Medical Document consumes the Stage-9 owner-issued reference through `get_exact()` and persists it as set-level ancestry. Recommendation IDs remain statement-level links and cannot reconstruct aggregate identity. PostgreSQL RLS, append-only reference history, payload integrity and predecessor validation make the Stage 9→11 path restart-safe.
## Exact terminology-governance lineage

Stage 4 issues shared-global exact references for persisted terminology mapping-governance records. Clinical Reasoning Input validates them through the Terminology owner query port and persists the ordered reference collection without duplicating mappings or concepts. The lineage is restart-safe and is distinct from the aggregate `terminology_version` marker.
## Release supply-chain boundary

Release security is an infrastructure boundary, not a medical bounded context. It binds the canonical package version, source revision, Alembic head, hash-locked dependencies, OCI artifact, SBOM/security reports and SLSA-compatible provenance in a signed, independently verifiable manifest. Domain/application layers do not import release infrastructure; deployment consumes only verified metadata. Institutional signing remains external through keyless CI or the existing KMS boundary.
# S003 Governed LLM Draft exact-reference boundary

The read-only Clinical Workspace may consume a governed draft only through the
owner-issued `PersistedGovernedLLMDraftReference` and `get_exact(reference)`.
The metadata-only reference binds the exact persisted draft version and predecessor,
tenant, invocation, PersistedGatewayInput, upstream artifact, policy, provenance,
content hash, integrity and current `ACTIVE` lifecycle. PostgreSQL RLS, append-only
enforcement and an independent replay checkpoint protect this boundary. Frozen
Gateway, Draft issuance and Human Review semantics remain unchanged.
