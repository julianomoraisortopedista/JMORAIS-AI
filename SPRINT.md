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
