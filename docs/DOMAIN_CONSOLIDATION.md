# Domain Consolidation and Immutability — ST-19

## Purpose

ST-19 is a corrective architecture sprint. It reduces parallel domain models and
business-rule implementations, establishes canonical ownership, and makes domain
values immutable where construction does not require controlled mutation. It adds
no medical capability and does not change the Scientific Core trust policy.

## Classification vocabulary

- **CANONICAL** — the sole domain definition used for new and supported flows.
- **ADAPTER** — infrastructure representation of a canonical domain concept; it is
  not a second domain definition.
- **DEPRECATED** — fail-closed compatibility tombstone with no business rules.
- **REMOVE_LATER** — retained temporarily to produce an explicit migration error.

## Duplicate inventory and ownership

| Concept | Canonical owner | Other occurrence | Classification and disposition |
|---|---|---|---|
| Scientific article | `jmoraIs.scientific_domain.ScientificArticle` | `jmoraIs.db.ScientificArticle` | CANONICAL domain / ADAPTER ORM |
| Citation | `jmoraIs.scientific_domain.Citation` | `jmoraIs.db.Citation` | CANONICAL domain / ADAPTER ORM |
| Evidence claim | `jmoraIs.scientific_domain.EvidenceClaim` for scientific records; `jmoraIs.evidence_ledger.Claim` for immutable ledger identity | `jmoraIs.db.EvidenceClaim` | Stage-specific canonical values / ADAPTER ORM. Their responsibilities are distinct and documented by package ownership. |
| Verification status | `jmoraIs.scientific_domain.VerificationStatus` | none | CANONICAL; duplicate definitions prohibited |
| Support direction | `jmoraIs.scientific_domain.SupportDirection` | none | CANONICAL; duplicate definitions prohibited |
| Evidence level | `jmoraIs.appraisal.domain.EvidenceLevel` | removed legacy clinical domain | CANONICAL |
| Recommendation strength | `jmoraIs.appraisal.domain.RecommendationStrength` | removed legacy clinical domain | CANONICAL |
| Appraised recommendation | `jmoraIs.appraisal.domain.AppraisedRecommendation` | governed clinical recommendation | CANONICAL appraisal-stage output, not a final clinical decision |
| Governed clinical recommendation | `jmoraIs.clinical.governed.GovernedClinicalRecommendation` | removed legacy `ClinicalRecommendation` | CANONICAL final clinical recommendation |
| Governed evidence | `jmoraIs.appraisal.governed.GovernedEvidence` | none | CANONICAL governed input |
| Reviewer identity and role | `jmoraIs.clinical.review_governance.ReviewerIdentity` and `ReviewerRole` | none | CANONICAL |
| Evidence package | `jmoraIs.application.evidence_packages.EvidencePackage` | persistence records | CANONICAL domain/application value / ADAPTER records |
| Package query port | `jmoraIs.application.ports.EvidencePackageQueryPort` | duplicate appraisal protocols removed | CANONICAL application port |
| Recommendation review service | `AuthorizedRecommendationReviewService` | `RecommendationReviewService` | CANONICAL / DEPRECATED REMOVE_LATER tombstone |
| Clinical intelligence service | `GovernedClinicalIntelligenceService` | legacy application and root engine | CANONICAL / DEPRECATED REMOVE_LATER tombstones |
| Repositories | Package catalog, governed decision audit, lifecycle and adjudication ports each own a distinct aggregate | in-memory and PostgreSQL implementations | CANONICAL ports / ADAPTER implementations; no duplicate business rules |
| Legacy recommendation domain | governed appraisal and clinical types above | former `jmoraIs.clinical.domain` | SAFE_TO_REMOVE_NOW; removed after confirming no supported consumer |
| Legacy clinical repository | governed audit and lifecycle repositories | former `jmoraIs.clinical.infrastructure` | SAFE_TO_REMOVE_NOW; removed after confirming no supported consumer |

`SearchRun` and similarly named database rows are domain/adapter pairs, not two
domain concepts. ORM classes remain infrastructure serialization and persistence
models and must not become imports of domain or application policy code.

## Canonical dependency direction

The supported flow is:

1. Scientific Core verifies and issues an `EvidencePackage`.
2. The canonical `EvidencePackageQueryPort` resolves package state without leaking
   a repository implementation.
3. Appraisal produces `AppraisedRecommendation` and `GovernedEvidence`.
4. Governed Clinical Intelligence accepts governed evidence only and emits
   `GovernedClinicalRecommendation`.
5. Authorized reviewer governance controls review transitions.
6. Infrastructure adapters implement ports and never define eligibility,
   verification, recommendation, or reviewer-authorization policy.

The old ST-12 clinical engine, application service, domain models, and in-memory
repository are not an alternative path. The unused domain and repository modules
were removed. Import-compatible service names that remain are fail-closed
tombstones and contain no medical or authorization rules.

## Immutability policy

Domain values and output records are frozen dataclasses. Collection fields are
represented as tuples, and nested mappings are read-only where they cross a public
boundary. ST-19 additionally applies this rule to scientific verification records,
deduplication decisions, audit outputs, medical document outputs, and executive
brief outputs.

Infrastructure/ORM models, database sessions, connector response construction,
and repository implementation state are outside the domain immutability rule.
They may be mutable only to perform their adapter responsibility.

### Intentional mutable exceptions

| Type | Reason | Boundary control | Future direction |
|---|---|---|---|
| `ScientificArticle` | Transitional working aggregate populated and reconciled across authoritative retrieval and verification steps | It is internal discovery/verification state and cannot cross the trust boundary as trusted evidence; only an integrity-validated `EvidencePackage` can do so | Replace mutation with a builder or explicit state-transition return values in a future corrective sprint |
| `SearchRun` | Retrieval orchestration records result count and terminal status as the run completes | It is an internal operational aggregate, not clinical evidence | Separate immutable completed-run snapshot from the mutable run coordinator |

These exceptions are exact and enforced by architecture tests. Adding another
mutable domain dataclass requires an explicit architecture decision and test update.

## Consolidated business rules

- Verification status and support direction are owned by the Scientific domain.
- Evidence hierarchy and recommendation strength are owned by Appraisal.
- Evidence eligibility is owned by the governed eligibility gate.
- Clinical recommendation construction is owned by Governed Clinical Intelligence.
- Reviewer authorization and review transitions are owned by Review Governance.
- Package lookup is expressed through one application port.
- Deprecated entry points fail closed and cannot reproduce these rules.

## Architecture enforcement

`tests/test_domain_consolidation_architecture.py` prevents:

- duplicate canonical enums and query ports;
- new mutable domain dataclasses outside the two documented exceptions;
- restoration of the removed legacy clinical domain/repository;
- business-rule growth in deprecated clinical entry points;
- export of legacy recommendation models from the public clinical boundary.

Existing trust-boundary, dependency-direction, persistence, governance, replay,
and Scientific Core architecture tests remain authoritative and run in the full
suite.

## Deferred normalization and debt

- The package name `jmoraIs` has inconsistent casing but renaming it is a breaking
  packaging migration and is outside this corrective sprint.
- ORM classes share domain-friendly names. Suffixing them with `Row` or `Model`
  would improve clarity but requires a migration-safe infrastructure refactor.
- The two mutable scientific working aggregates should become builder/coordinator
  types plus immutable completed snapshots.
- Deprecated tombstones should be removed in a versioned breaking release after
  downstream import telemetry or a migration window confirms they are unused.
- Audit, document, and executive modules remain outside the governed medical path;
  their immutable outputs do not authorize them to consume trusted evidence.

## ST-19 exit condition

ST-19 is approvable when the complete test suite, coverage run, architecture tests,
and `git diff --check` pass, and no canonical type or business rule listed above
has a parallel active implementation.
