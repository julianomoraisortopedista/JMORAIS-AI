# BETA Release Inventory — ST-22

## ST-23 classification addendum

- `INCLUDE_IN_BETA`: domain/application/infrastructure sources, migrations, role SQL, tests, workflows, Docker assets, governed benchmark dataset/builders and release documentation.
- `NEEDS_REVIEW`: every accumulated tracked modification and untracked source from ST-18–ST-23 until a reviewed candidate diff is composed.
- `GENERATED`: live benchmark JSON reports, coverage XML, `dist/`, `build/` and egg metadata.
- `LOCAL_ONLY` / `EXCLUDE`: `UNKNOWN.egg-info/`, caches, virtual environments, local databases/dumps, `.env` and IDE state.
- `DEPRECATED`: compatibility modules explicitly identified by architecture tests; removal requires a separate reviewed change.

The ST-23 sensitive-data scanner reported zero findings after the README absolute developer path was removed. No database dump or credential file was found.

## Branch and release state

- Branch: `feature/scientific-core-v0.2`.
- Remote baseline: `origin/feature/scientific-core-v0.2` at `7fdf902`.
- ST-18–ST-22 work is present in the working tree but is not a remote, tagged or
  reproducible release artifact.
- No commit, push, merge or tag is performed by ST-22.

## Git index lock inspection

`.git/index.lock` was not present when ST-22 inspected it. The previous audit had
observed it, so it was transient or removed outside this sprint. Sandbox restrictions
prevented process enumeration with `ps`; no lock was deleted and no unsafe cleanup
was attempted. Before the eventual commit, the release owner must confirm no active
Git process and recheck the lock.

## Working-tree inventory

The tree contains tracked modifications and untracked additions spanning:

- Scientific Core authoritative verification, reconciliation and Vancouver gate;
- Evidence Ledger, EvidencePackage catalog and automatic revocation;
- governed appraisal, Clinical Intelligence, reviewer governance and persistence;
- PostgreSQL migrations 004–008, concurrency controls and checkpoints;
- cryptographic replay and tamper tests;
- benchmark infrastructure and live benchmark workflow;
- CI, Python 3.12/PostgreSQL 16 test environment and release documentation.

Ignored local artifacts are correctly excluded: `.coverage`, `.pytest_cache/`,
`__pycache__/`, virtual environments, `.env`, SQLite/database files and editor state.

## Required release composition

The eventual reviewed release must intentionally include:

- `jmoraIs/application`, `appraisal`, `clinical`, `infrastructure`, connectors and
  scientific domain modules;
- Alembic configuration and migrations 004–008;
- database role provisioning;
- all architecture, unit, PostgreSQL, concurrency, replay, identity, logging,
  backup/restore and performance tests;
- `.github/workflows/ci.yml` and `live-scientific-benchmark.yml`;
- Docker/Python 3.12/PostgreSQL 16 reproducibility assets;
- governing and release-readiness documentation.

## Pre-commit release checks

1. Confirm no Git process and no `.git/index.lock`.
2. Review every untracked file and exclude local artifacts/secrets.
3. Run mandatory CI commands from a clean clone.
4. Review migrations and role provisioning separately.
5. Verify the live benchmark dataset license and provenance.
6. Create one reviewed PR; do not collapse evidence through an unreviewed direct push.
7. Tag only the commit that produced the retained test, migration and replay reports.
