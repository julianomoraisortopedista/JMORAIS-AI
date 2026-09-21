# BETA Release Composition — ST-23

## Candidate

- Proposed version: `0.2.0-beta.1` (first prerelease containing the hardened Scientific Core and governed clinical path).
- Included sprints: ST-18 through ST-23.
- Migration head: `008_reviewer_identity`.
- Runtime: Python 3.12.13; PostgreSQL 16.
- Benchmark: `authoritative-biomedical-v2.0.0`.
- Scientific Core: `SC-v1`; governance/authorization policy: `ST-22.1`.
- No tag, commit, push or merge is performed by this sprint.

## Include in the reviewed candidate

Domain/application/infrastructure changes under `jmoraIs/`; benchmark source and governed dataset under `evaluation/`; Alembic revisions and PostgreSQL roles; deterministic and integration tests; Python/PostgreSQL Docker assets; CI and benchmark workflows; operational scripts; architecture, security, policy and release documentation.

## Exclude

`UNKNOWN.egg-info/`, caches, coverage outputs, local environments, `.env`, database/dump files, IDE state, generated live reports containing transient operational results unless explicitly retained as signed CI artifacts. Deprecated compatibility modules require reviewer confirmation before inclusion.

## Migration and CI sequence

Install `.[dev]`; start empty PostgreSQL 16; run `alembic upgrade head`; verify current head; apply least-privilege roles; run source hygiene, dependency check, full pytest with coverage ≥90%, PostgreSQL integration tests, packaging build and `git diff --check`. Run live benchmark, representative restore/replay and performance suite separately.

## Evidence references and limitations

Two accepted benchmark runs and their assessments are under `evaluation/scientific_benchmark/reports/`. Backup procedure is in `BACKUP_RESTORE_REPLAY.md`; performance budgets are in `PERFORMANCE_BUDGETS.md`. Current limitations include incomplete representative restore evidence, missing scale measurements, production IAM/RLS/secrets/alert delivery and prospective clinical validation.

## Rollback

Deploy only immutable versioned artifacts. On failure, stop writers, preserve logs and database, validate replay, restore the last verified backup into an isolated database and redeploy the preceding artifact. Append-only migrations have no destructive downgrade; never erase ledger history.

## Checklist

- [ ] Every file classified and independently reviewed
- [ ] No secrets/sensitive data
- [ ] Empty-database migrations and role grants pass
- [ ] Deterministic suite and coverage gate pass
- [x] Two consecutive accepted live benchmarks
- [x] Populated backup/restore/replay equivalence passes
- [x] Performance budgets pass at representative scale
- [ ] Known limitations and release decision approved
