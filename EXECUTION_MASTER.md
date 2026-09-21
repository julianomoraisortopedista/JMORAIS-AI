# JMORAIS-AI — EXECUTION MASTER

Version: 1.0
Status: ACTIVE

## Mission

Este documento é a fonte única de verdade da execução do projeto.

Ele governa:

- arquitetura
- roadmap
- sprint ativa
- critérios de parada
- governança
- execução contínua

---

# Current Status

Platform Status:

READY FOR CONTROLLED INTERNAL PILOT

Último gate aprovado:

- COMPLETE_CASE 1→14
- RC1 Runtime Security
- RC1 Offline Replay
- RC1 Supply Chain
- RC2 Performance & Scalability

---

# Frozen Modules

Os módulos abaixo somente poderão sofrer alterações mediante impacto arquitetural comprovado.

- Patient Context
- Terminology
- Evidence Engine
- Clinical Appraisal
- Governed Evidence
- Clinical Reasoning
- Guideline Engine
- Orthopedic Intelligence
- Medical Documents
- Audit Defense
- Gateway
- Governed LLM Draft
- LLM Invocation Exact Reference
- Medical Document Exact Reference
- Human Review Exact Reference
- Human Review
- Replay
- Runtime Security
- Offline Replay
- Supply Chain
- FHIR Interoperability
- SMART on FHIR Authentication

---

# Permanent Engineering Rules

Sempre:

- Clean Architecture
- DDD
- Fail Closed
- Restart Safe
- PostgreSQL Source of Truth
- Append Only
- Replay VALID
- Exact Reread
- Owner-issued References
- Human Review obrigatório
- Provenance completa
- RLS obrigatório

Nunca:

- latest()
- history scan
- reconstrução por escalares
- payload duplicado
- bypass RLS
- replay parcial
- wrappers de confiança

---

# Current Execution

Approved S003 exact-reference boundaries:

- Patient Context
- Clinical State
- Clinical State Timeline
- Governed Evidence
- Governed LLM Draft

Current canonical schema revision:

- `057_human_review_exact_ref`

Sprint ativa:

SPRINT.md

Roadmap:

ROADMAP.md

Histórico:

CHANGELOG.md

---

# Execution Policy

Cada nova sessão deverá:

1. Ler este documento.
2. Ler SPRINT.md.
3. Executar apenas a Sprint ativa.
4. Não revalidar módulos FROZEN.
5. Atualizar CHANGELOG.md quando concluir uma Sprint.
6. Parar imediatamente diante de qualquer blocker.

Fim.

## Checkpoint S003

Clinical Reasoning Input preserva upstream lineage metadata-only e tipada para
Clinical State, Governed Evidence e Terminology Governance. A montagem valida
referências owner-issued pelos respectivos `get_exact`; versões legadas não
recebem ancestry sintética. O boundary expõe agora
`PersistedClinicalReasoningInputReference → get_exact(reference)` com checkpoint
de completude. Orthopedic Assessment preserva a mesma referência exata de
Clinical Reasoning consumida na geração. Schema atual: Alembic `060`.
