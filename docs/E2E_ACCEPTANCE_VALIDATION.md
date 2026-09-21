# E2E Acceptance Validation

At Stage 14, AuditDefense-backed drafts use `UpstreamReviewGovernanceRouter` and the Audit Defense owner adapter after runtime restart. The adapter recovers the exact final package through its opaque persisted reference and preserves Stage-11 lineage, critical conflicts and self-approval attribution.

Stage 12→13 transports only the owner-issued `PersistedDefensePackageReference` across a restart boundary. The test-only adapter may call the owner query port's `get_exact(reference)` and pass the returned package to `issue_from_package()`, but it may not extract stream/version, use `latest()`, or create a replacement reference.

The test-only harness in `evaluation.e2e_acceptance` defines the approved canonical validation sequence: Authorized Ingestion → Patient Context → Clinical State → Terminology → EvidencePackage → Clinical Appraisal → GovernedEvidence → ClinicalReasoningInput → Guideline Recommendation Set → Orthopedic Assessment → Medical Document → Audit Defense → LLM Gateway → Human Review. It contains no clinical policy and is not imported by production composition. Each `PersistedStagePort` adapter must call the owning bounded-context application service, persist its result, release process-local state, reread through the canonical query port and describe a reference-only handoff.

The earlier twelve-stage sequence was invalid because it placed ClinicalReasoningInput before terminology and governed evidence, despite the contract requiring `terminology_version`, EvidencePackage-linked GovernedEvidence and applicable guideline-source references. EvidencePackage and Clinical Appraisal were also absent. Guideline source/reference metadata is an input prerequisite; `GuidelineRecommendationSet` is a later output, so this distinction avoids a cycle without changing the protected contract.

The execution identity is synthetic and contains execution/case, tenant, organization, authorized principal, purpose, correlation and policy versions. Direct patient identifiers and clinical payloads are prohibited. Stage states are `NOT_STARTED`, `RUNNING`, `BLOCKED`, `REVIEW_REQUIRED`, `COMPLETED` and `FAILED`.

The trace manifest references all fourteen approved stages, including EvidencePackage and Clinical Appraisal ancestry before GovernedEvidence and ClinicalReasoningInput. A missing reference, version or provenance link makes the manifest incomplete.

Blocked cases stop immediately and never fabricate downstream trace entries. Required acceptance scenarios are complete, missing data, conflicting data, stale data, critical guideline conflict and revoked evidence. The complete case must use canonical reviewer authorization and the governed mock LLM provider; approval never enables external clinical actionability.

For restart validation, persist through an intermediate stage, dispose database/application resources, reconstruct stage adapters and continue using only stored references. The final run must execute cryptographic replay and require `VALID` without rewriting history.

## Controlled-pilot release evidence

The canonical `COMPLETE_CASE` now executes all fourteen stages continuously with
production services, repositories, ports and PostgreSQL adapters. It persists and
rereads every owner artifact, disposes runtime resources at the mandatory
boundaries, reconstructs the complete ancestry through exact typed references and
persists a tenant-scoped, append-only reference manifest. The validation remains a
test composition and does not introduce a production mega-orchestrator.

The release proof requires a clean disposable database because tamper-detection
tests intentionally corrupt their isolated streams. On that clean database the
global cryptographic replay decision is `VALID`, every reported stream has verified
completeness, the final human-reviewed output remains non-actionable, and a second
tenant cannot read the case or its manifest.

The fail-closed scenario suite proves missing data, conflicting data, stale data,
critical guideline conflict, revoked evidence and invalidated draft behavior. These
scenarios stop at their owning policy boundary and do not fabricate downstream
artifacts.

Stage 1 and Stage 2 now have concrete validation-only adapters. Stage 1 invokes
`ClinicalIngestionService`, verifies the atomically persisted
`AuthorizedClinicalIngestionRecord`, releases local state and rereads it by exact
ID. Stage 2 follows that record's exact PatientContext ID/version and rereads the
canonical aggregate without a second write. The remaining full 1→14 continuous
composition is still a separate acceptance gate.

Patient Context also owns the exact persisted-reference boundary required by
future interoperability flows. An owner-issued reference binds Stage 1's
authorized-ingestion record to one exact Stage 2 context version. Restart-safe
resolution uses `get_exact(reference)` only; legacy reads do not establish this
stronger trust relationship and no latest/history/scalar fallback is permitted.

The Stage-11/Stage-12 ancestry uses an immutable workflow reference rather than a
false reasoning dependency. A new append-only `DefensePackage` version carries an
exact `MedicalDocumentVersionReference`, issued from the canonical persisted
document repository under the same tenant. Backward trace must resolve that exact
version and integrity; correlation alone is insufficient. This does not make
Medical Document prose an Audit Defense input.

Stage 13 now has a canonical restart-safe input-trust segment. The invocation
references an append-only `PersistedGatewayInputRecord`; after restart the record
resolves the exact owner artifact version, recomputes the canonical DTO hash and
verifies the original HMAC using the managed-key reference. The DTO is never stored
in this trust record. Legacy invocations without this link cannot satisfy the final
manifest. This focused proof does not replace execution of the full 1→14 case.
For an Audit Defense upstream, the validation adapter passes the typed final
`DefensePackage` directly to the owner issuer and never extracts stream/version
strings to call a scalar trust API. The issuer revalidates canonical persistence;
the resulting record preserves the exact final package identity for reverse trace.

Stage 9→11 uses an owner-issued exact guideline-set reference. After restart,
Stage 11 resolves the precise persisted `GuidelineRecommendationSet` through
`get_exact(reference)` and stores the same reference in the document. Backward
trace may not substitute `latest()`, scan history or infer ancestry from
recommendation IDs. Legacy documents without this reference are excluded from
COMPLETE_CASE evidence.

Stage 4→8 transports only the deterministic tuple of owner-issued
`PersistedTerminologyMappingGovernanceReference` values. The test-only handoff
does not extract concept/version scalars or recreate references. Stage 8 resolves
each record through `get_exact()` before persisting the same ancestry.

Stage 10→11 uses an owner-issued `PersistedOrthopedicAssessmentSetReference`.
Controlled-pilot document generation resolves it through `get_exact(reference)`
after runtime disposal and stores the same typed reference in
`MedicalDocumentVersion`. Historical documents without it remain explicitly
`LEGACY_MISSING_ORTHOPEDIC_ASSESSMENT_REFERENCE`; scalar set ID/version fields
never independently establish trusted ancestry.
