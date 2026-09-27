# Sprint S005 — Minimal Clinical Workspace UI

Status: DONE — SOFTWARE BOUNDARY — 2026-09-27.

Seven read-only viewers, authenticated shell, configurable public-client OIDC
Code + PKCE S256, prospective exact ClinicalWorkspaceLaunch and secure bootstrap.
Existing IAM/tenant/organization authorization and clinical exact-owner reads
remain authoritative. No clinical browser persistence or historical backfill.

Evidence: 21 PostgreSQL/API/runtime tests PASS; 7 frontend tests PASS;
15 launch/architecture unit tests PASS; typecheck, lint, production build and
git diff --check PASS. PostgreSQL 16.14; current=head `066_workspace_launch`.
Detailed evidence and limits: PROJECT_STATE.md; `/tmp/s005-launch-focused.log`.
Integration uses protocol fixtures plus real PostgreSQL/authenticated API tests.
Real-browser automation is POST_RELEASE, not a new S005 requirement.

EXTERNAL OIDC CLIENT REGISTRATION = PENDING (deployment prerequisite).
NEXT MILESTONE: PRODUCT RELEASE CLOSURE / INTERNAL PILOT RUNTIME. Not started.

---

## Historical S004 checkpoint

# Sprint S004 — API / Presentation Boundary

Status: DONE — 2026-09-23.

Seven read-only Workspace resolve routes plus authenticated context are composed
through existing production/homologation runtime and exact owner ports. Tenant
isolation, RLS/read-only transactions, secure errors and authoritative prospective
Governed Draft signing-key binding are preserved. Historical unbound drafts remain
FAIL-CLOSED / NO BACKFILL. No new migration.

Final gate: 958 passed, 8 skipped; coverage 94.00417476426978%.
PostgreSQL 16.14 / Alembic current == head `065_defense_reference_state`.
COMPLETE_CASE 1→14, global replay, runtime composition, auth/tenant, RLS/restart,
exact-reference trust-path hygiene, pip check, compileall and diff check: PASS.
Evidence: PROJECT_STATE.md and `/tmp/s004-final2-coverage.log`.

NEXT ACTION: MINIMAL CLINICAL WORKSPACE UI planning. Not implemented.
POST_RELEASE: existing Starlette/httpx deprecation warning.

---

## Historical S003 checkpoint

# Sprint S003

Status:

DONE

Release Train:

Clinical Applications

---

# Objetivo

Construir o primeiro Clinical Workspace read-only sobre informações canônicas já
existentes, sem nova inteligência clínica, inferência, evidência ou execução LLM.

---

# Pré-requisito concluído

Clinical State agora expõe exclusivamente para a futura composição S003:

- `PersistedClinicalStateReference → get_exact(reference)`;
- `PersistedClinicalStateTimelineReference → get_timeline_exact(reference)`.

As duas referências são owner-issued, metadata-only, append-only, restart-safe,
tenant-scoped e protegidas por RLS. Nenhum `latest()`, `history(patient_id)`,
`at(patient_id, as_of)` ou escalar fornecido pelo consumidor estabelece confiança.

Governed Evidence agora expõe também:

- `PersistedGovernedEvidenceReference → get_exact(reference)`.

A referência vincula a versão canônica persistida, EvidencePackage, appraisal,
policy, provenance e lifecycle `ACTIVE`. O stream é tenant-scoped, append-only,
RLS-protected e incluído no Offline Replay por checkpoint independente.

Governed LLM Draft agora expõe exclusivamente para o futuro LLM Trace Viewer:

- `PersistedGovernedLLMDraftReference → get_exact(reference)`.

A referência owner-issued vincula versão/predecessor exatos, invocation,
PersistedGatewayInput, upstream artifact, policy, provenance, hashes e lifecycle
`ACTIVE`. O stream de referências é metadata-only, append-only, RLS-protected,
restart-safe e coberto por checkpoint independente no Offline Replay.

LLM Gateway agora emite `PersistedLLMInvocationReference` somente após igualdade
exata com a invocação, contexto, PromptVersion e PersistedGatewayInput persistidos.
Novas referências exatas de Governed LLM Draft vinculam obrigatoriamente essa
referência tipada; referências antigas permanecem imutáveis, mas são classificadas
como `LEGACY_MISSING_PERSISTED_LLM_INVOCATION_REFERENCE` para fins da S003.

Medical Documents agora emite:

- `PersistedMedicalDocumentVersionReference → get_exact(reference)`.

O contrato é owner-issued, metadata-only, append-only, tenant-scoped, RLS-protected
e restart-safe. A referência preserva a versão/predecessor exatos, integridade,
proveniência, traceability e os vínculos tipados de Guideline/Orthopedic. O contrato
legado Stage 11→12 permanece operacional, mas não estabelece confiança para a S003.

Human Review agora emite:

- `PersistedHumanReviewReference → get_exact(reference)`.

A referência vincula o evento histórico exato ao
`PersistedGovernedLLMDraftReference`, preserva reviewer, decisão, estado resultante,
posição/predecessor/hash-chain, tenant e policy. O caminho S003 não usa
`current_state()`, `history()` ou escalares de draft/version.

---

# Escopo concluído S003

- Patient Timeline;
- Patient Summary;
- Patient Context Viewer;
- Clinical State Viewer;
- Evidence Explorer;
- Guideline Explorer;
- Medical Document Viewer;
- Audit Defense Viewer;
- Human Review Viewer;
- Explainability Viewer;
- busca determinística somente sobre metadados canônicos.

---

# Restrições

Read-only. Sem escrita, raciocínio novo, inferência clínica, nova evidência,
embeddings, banco vetorial, cache process-local ou execução LLM.

---

# Checkpoint

S003 DONE — 2026-09-21. Clinical Workspace read-only e referências exatas
concluídos. Alembic current == head: `065_defense_reference_state`.
Gate final: 942 passed, 8 skipped; cobertura 93.85670618057108%.
COMPLETE_CASE 1→14, global replay, PostgreSQL 16, RLS/restart, arquitetura
read-only, trust-path hygiene, pip check, compileall e git diff --check: PASS.
Evidências e distinção entre validações existentes e renovadas: PROJECT_STATE.md.

NEXT ACTION: S004 — API / Presentation Boundary planning.
Plano de fechamento: RELEASE_FINISH_PLAN.md. S004 não implementada.
