# JMORAIS-AI engineering invariants

- Python 3.12; Clean Architecture and existing bounded-context owners.
- Owner-issued typed exact references; trusted reads use `get_exact` / approved exact ports.
- No `latest()`, `history()`, `at()`, scalar reconstruction or inferred versions in trusted resolution.
- Fail closed; preserve authenticated principal, tenant, organization, purpose and IAM authorization.
- Tenant isolation/RLS; API runtime remains NOBYPASSRLS.
- Trusted history is append-only; preserve cryptographic completeness, replay and tamper evidence.
- Historical lifecycle provenance and current eligibility are separate owner authorities.
- No synthetic provenance, historical backfill, inferred signing keys or re-signing.
- Human Review remains mandatory before external clinical actionability.
- No secrets in repository, logs, errors or browser persistence.
- Never weaken security to satisfy tests; no speculative release refactoring.
- No commit, push or merge without explicit authorization. Preserve local changes.

`PROJECT_STATE.md` is current operational memory.
The repository-owned software release gate is `make release-candidate`;
operator instructions are in `INTERNAL_PILOT_RUNBOOK.md`.

During RELEASE CLOSURE, diagnose and correct ordinary test/runtime/fixture failures
autonomously. Use focused proof, then subsystem and release gates.
Stop only for a new trust/security architectural decision, destructive/non-test
data risk, a correction requiring weaker validated security, or an essential
external dependency preventing further software validation.
