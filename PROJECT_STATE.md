# PROJECT STATE

## Project

JMORAIS-AI

## Mode

ULTRA LOW TOKEN EXECUTION MODE

## Current Sprint

S003 — Clinical Workspace Read-Only

## Sprint Status

DONE

## Approved Prerequisites

- Patient Context Exact Reference — PASS
- Clinical State Exact Reference — PASS
- Clinical State Timeline Reference — PASS
- Governed Evidence Exact Reference — PASS
- Governed LLM Draft Exact Reference — PASS
- Medical Document Exact Reference — PASS
- Human Review Exact Reference — PASS
- Clinical Reasoning Exact Upstream Lineage — PASS
- Clinical Reasoning Input Exact Reference — PASS
- Orthopedic → Clinical Reasoning Exact Lineage — PASS
- Audit Defense Exact Reference Resolution — PASS
- PGI → Defense Package Exact Reference Linkage — PASS
- Audit Defense In-Memory Exact Resolution — PASS
- Audit Defense Gateway Exact Resolution — PASS
- PostgreSQL Native SHA256 Checkpoint Fix — PASS
- Audit Defense persisted-reference cryptographic completeness — PASS
- Audit Defense PRE_LINK → STAGE11_LINKED exact reference — PASS
- Audit Defense → Medical Document exact Stage-11 lineage — PASS
- Clinical Workspace first read-only viewers — PASS
- Clinical Workspace remaining read-only viewers — PASS

## Current Checkpoint

S003 final validation gate — PASS (2026-09-21).

Most recent migration (unchanged):

`065_defense_reference_state`

Timeline, Medical Document, Human Review and Audit Defense viewers compose immutable metadata through existing owner-approved exact query ports. Timeline uses only `get_timeline_exact(reference)` and preserves owner-controlled member ordering. Other viewers use `get_exact(reference)`; STAGE11_LINKED also rereads its exact Medical Document reference. PRE_LINK remains explicitly unlinked. Source references retain version, predecessor, tenant, provenance/integrity and traceability metadata. Replay is explicitly NOT_EVALUATED and completeness is unknown: an exact read is not a replay attestation. No clinical mutations, new trust contracts, frozen-module changes, frontend or API.

Focused validation: 15 tests passed (1 architecture/source-hygiene, 14 PostgreSQL integration cases). PostgreSQL 16: Alembic current == head (`065_defense_reference_state`). Same-tenant reads pass; cross-tenant/missing TenantContext, invalid references/hashes, reordered timeline references and deleted persisted references fail closed. Missing timeline member, Stage-11 document and governed draft dependencies also fail closed; all deletion probes rolled back. Reader transactions are read-only, NOSUPERUSER and NOBYPASSRLS, with no DML in monitored viewer queries. CLINICAL_WORKSPACE_REMAINING_VIEWERS_EXACT_REREAD = PASS after disposal and fresh reader/owner/workspace composition; results are deterministically equivalent. Focused source hygiene, compileall and `git diff --check`: PASS. This focused checkpoint preceded the final gate recorded below.

## Final Gate Evidence

- Full pytest: 942 passed, 8 skipped, 1 deprecation warning; final run 36.85s.
- Coverage: 93.85670618057108% (12,589 / 13,413 statements), above 90%.
- Evidence: `/tmp/s003-final-coverage.log`, `/tmp/s003-final-coverage.json`.
- PostgreSQL 16 / Alembic current == head: `065_defense_reference_state` — PASS.
- COMPLETE_CASE 1→14, global replay, RLS/restart: PASS; accepted existing evidence retained without repeating expensive validations.
- Read-only architecture / exact trust paths: PASS through approved focused checks and final suite.
- pip check: PASS from existing gate evidence.
- source hygiene, compileall (jmoraIs/evaluation/tests), git diff --check: PASS, refreshed at closure.
- S004 not implemented. Release planning: `RELEASE_FINISH_PLAN.md`.

## Current Blocker

None for S003 closure.

## Next Action

S004 — API / Presentation Boundary planning.

## Frozen / Approved

Do not re-audit unless directly affected:

- Patient Context
- Clinical State
- Terminology
- Evidence Engine
- Clinical Appraisal
- Governed Evidence
- Clinical Reasoning
- Guideline Engine
- Orthopedic Intelligence
- Medical Document
- Audit Defense reasoning semantics
- LLM Gateway
- Governed LLM Draft
- Human Review
- FHIR MVP
- SMART on FHIR
- Runtime Security
- Supply Chain Security
- RC1
- RC2

## Permanent Trust Rules

Always:

- owner-issued references
- `get_exact(reference)`
- fail-closed
- restart-safe
- append-only
- RLS
- cryptographic replay
- checkpoint completeness
- Human Review

Never use as trust source:

- `latest()`
- `history()`
- `at()`
- free scalar IDs
- inferred versions
- retained process-local objects
- synthetic backfill
- validation-only trust wrappers

## Validation Policy

During prerequisites:

- focused unit tests only
- focused architecture tests only
- focused PostgreSQL tests when required
- no full pytest
- no COMPLETE_CASE
- no RC1/RC2 benchmarks

At S003 completion only:

- PostgreSQL 16
- Alembic current/head
- full pytest
- coverage >= 90%
- COMPLETE_CASE 1→14
- global replay
- restart
- RLS
- pip check
- git diff --check
- source hygiene
- compileall

## Repository Safety

Do not:

- commit
- push
- merge
- reset
- checkout destructively
- discard uncommitted S003 work

## State Update Policy

After each prerequisite:
update only:

- last approved item
- current blocker
- next action

Do not reconstruct historical project state.
