# CHANGELOG

Todas as alterações relevantes do JMORAIS-AI devem ser registradas neste documento.

O objetivo é preservar somente entregas concluídas e aprovadas.

Não registrar:
- planejamento;
- tarefas futuras;
- análises;
- auditorias;
- hipóteses;
- blockers temporários.

---

# S005 — Minimal Clinical Workspace UI — 2026-09-27

Status: DONE — SOFTWARE BOUNDARY.

- Seven read-only viewers and authenticated shell over the approved S004 API.
- Public-client OIDC Code + PKCE S256 with configurable public metadata, state/nonce validation, callback cleanup and memory-only access token.
- Prospective ClinicalWorkspaceLaunch with exact owner validation, principal/tenant/organization binding, append-only/RLS persistence and checkpoint/replay integration. Migration `066_workspace_launch`; no historical backfill.
- Read-only bootstrap transports stored exact references unchanged; secure errors and no-store behavior.
- Evidence: 21 focused PostgreSQL/API/runtime tests, 7 frontend tests and 15 launch/architecture unit tests PASS; typecheck/lint/build/diff check PASS. PostgreSQL 16.14/current=head `066_workspace_launch`.
- Software completion does not assert institutional OIDC registration or live-pilot deployment readiness.

---

# S004 — API / Presentation Boundary — 2026-09-23

Status: DONE.

- Seven read-only Clinical Workspace API viewers and authenticated caller context.
- Existing production/homologation composition supplies exact owner repositories; tenant isolation, RLS, secure errors and read-only behavior validated.
- Explicit managed Governed Draft SIGNING_KEY binding persisted in signed JSON; restart verification preserved. Historical unbound drafts fail closed without backfill. No migration.
- Obsolete test compositions and exact-class detectors corrected; COMPLETE_CASE database isolated from prior tamper probes.
- Final gate: 958 passed, 8 skipped; coverage 94.00417476426978%. PostgreSQL 16.14; Alembic current == head `065_defense_reference_state`.
- COMPLETE_CASE 1→14, global replay, runtime/auth/RLS/restart, API trust-path hygiene, pip check, compileall and diff check: PASS.

---

# S003 — Clinical Workspace Read-Only — 2026-09-21

Status: DONE.

- Viewers read-only sobre referências exatas emitidas pelos owners.
- Audit Defense: completude criptográfica de referências, estados PRE_LINK / STAGE11_LINKED e lineage exata Stage11.
- Composição exata dos adapters Stage11/12 e Stage13 validada.
- PostgreSQL 16; Alembic current == head `065_defense_reference_state`.
- Gate final: 942 testes aprovados, 8 ignorados; cobertura 93.85670618057108%.
- COMPLETE_CASE 1→14, global replay, RLS/restart, arquitetura read-only e higiene: PASS.

---

# [0.2.0-beta.1]

Status:

READY FOR CONTROLLED INTERNAL PILOT

## Arquitetura

### Adicionado

- Clean Architecture consolidada.
- Domain-Driven Design consolidado.
- Bounded Contexts independentes.
- Source of Truth baseada em PostgreSQL.
- Persistência append-only.
- Replay criptográfico.
- Exact reread.
- Owner-issued references.
- Restart-safe architecture.
- Human Review obrigatório.
- Provenance completa.
- Row-Level Security (RLS).
- Offline Replay Verifier.
- Runtime Security.
- Supply Chain Security.

---

## Clinical Core

### Adicionado

- Patient Context.
- Terminology Engine.
- Evidence Engine.
- Clinical Appraisal.
- Governed Evidence.
- Clinical Reasoning.
- Guideline Engine.
- Orthopedic Intelligence.

---

## Medical Layer

### Adicionado

- Medical Document Engine.
- Audit Defense Engine.
- Canonical LLM Gateway.
- Governed LLM Draft.
- Human Review Governance.

---

## Segurança

### Adicionado

- Cryptographic Replay.
- Offline Replay Boundary.
- Runtime Security Hardening.
- Supply Chain Validation.
- Exact Traceability.
- Cryptographic Checkpoints.
- Append-only enforcement.
- Secrets/KMS boundary.

---

## Persistência

### Adicionado

- Canonical PostgreSQL persistence.
- Exact-version repositories.
- Restart reconstruction.
- Immutable references.
- Cryptographic integrity validation.

---

## Governança

### Adicionado

- COMPLETE_CASE 1→14.
- Backward Trace 14→1.
- Manifest persistido.
- Replay VALID.
- RLS A/B.
- Restart validation.
- Human Review enforcement.

---

## Release Gates

### Aprovado

- COMPLETE_CASE 1→14.
- RC1 Runtime Security.
- RC1 Offline Replay Boundary.
- RC1 Supply Chain Security.
- RC2 Performance & Scalability.

---

## Validação

Última validação conhecida:

- COMPLETE_CASE: PASS
- Replay: VALID
- Restart: PASS
- RLS: PASS
- Append-only: PASS
- Coverage: >=90%
- PostgreSQL: PASS

---

## Estado Atual

Arquitetura:

FROZEN

Status do software:

READY FOR CONTROLLED INTERNAL PILOT

---

# [0.3.0-s001]

Data: 2026-09-01

Status: SPRINT S001 CONCLUÍDA

## Clinical Applications

### Adicionado

- Boundary de interoperabilidade HL7 FHIR R4 `4.0.1`.
- Importação governada dos 14 recursos definidos pelo FHIR MVP.
- Validação estrutural, semântica e de limites fail-closed.
- Resolução determinística de referências internas sem acesso de rede.
- Mapeamento determinístico para ingestão clínica canônica.
- Atualização incremental por `PersistedPatientContextReference` exata.
- Idempotência restart-safe reconstruída de metadados canônicos persistidos.
- Documentação de integração, mapeamento e segurança FHIR.

## Impacto arquitetural

- PatientContext permanece o único Source of Truth clínico.
- FHIR permanece uma fronteira de entrada e não atravessa bounded contexts
  congelados.
- Privacidade, terminologia, RLS, restart, replay e Human Review permanecem
  preservados.
- Nenhum payload FHIR bruto é persistido no domínio clínico.

## Validação

- PostgreSQL 16: PASS.
- Alembic `051_patient_context_exact_ref`: PASS.
- FHIR PatientContext handoff v1/v2: PASS.
- RLS e negativos de segurança: PASS.
- COMPLETE_CASE 1→14: PASS.
- Suíte integral: 853 passed, 8 skipped.
- Coverage: 94%.

---

# [0.3.0-s002]

Data: 2026-09-01

Status: SPRINT S002 CONCLUÍDA

## Clinical Applications

### Adicionado

- Boundary de autenticação protocolar SMART on FHIR.
- Parsing determinístico de SMART/OIDC discovery e JWKS.
- Validação de access token e ID token com assinatura e claims obrigatórias.
- PKCE S256 fail-closed.
- Parsing bounded de SMART scopes e launch context.
- Auditoria metadata-only integrada ao histórico IAM append-only.

## Impacto arquitetural

- IAM canônico permanece a única autoridade de identidade, tenant e policy.
- SMART on FHIR não autoriza operações clínicas nem cria PatientContext.
- Nenhum JWT, refresh token, segredo, PHI ou payload clínico é persistido.
- Não foi criada persistência clínica nem uma segunda identidade autoritativa.

## Validação

- Python 3.12.13: PASS.
- PostgreSQL 16 e restart: PASS.
- COMPLETE_CASE 1→14: PASS.
- Suíte integral: 861 passed, 8 skipped.
- Coverage: 94.29%.
- Source hygiene, pip check, compileall e git diff --check: PASS.

---

# Política deste arquivo

Registrar apenas mudanças permanentes.

Cada nova entrada deve conter:

- versão;
- data;
- alteração;
- impacto arquitetural.

Não remover histórico.

Não reescrever versões anteriores.

Este documento é append-only.
