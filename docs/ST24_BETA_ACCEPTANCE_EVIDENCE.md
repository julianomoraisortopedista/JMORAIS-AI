# ST-24 Beta Acceptance Evidence

## Benchmark

The governed v2 dataset contains 128 real records, 20 controlled negative cases and 78 real authoritative conflict cases. Of 105 eligible current records, 101 persist PubMed, Crossref and OpenAlex observations. Four persist source-unavailability reasons. Conflict outcomes fail closed or require explicit corrected-version re-verification.

## Representative recovery

The retained report `evaluation/release_evidence/representative-restore-replay.json` covers Scientific Ledger, two EvidencePackage versions, two GovernedEvidence versions, lifecycle events, reviewer identity/actions, conflict adjudication and audit. The database was backed up, its schema destroyed, restored, replayed and compared. Result: `VALID`, 8 streams, 114 verified events and identical deterministic state hash.

## Performance

| Profile | Events | Append p95 | Append throughput | Single replay | Full replay | Max RSS | DB size |
|---|---:|---:|---:|---:|---:|---:|---:|
| SMALL | 100 | 0.216 ms | 4,632/s | 0.0037 s | 0.0141 s | 63 MB | 10 MB |
| MEDIUM | 10,000 | 1.858 ms | 1,619/s | 0.2705 s | 0.2421 s | 112 MB | 44 MB |
| LARGE | 100,000 | 1.379 ms | 3,398/s | 2.9674 s | 3.9963 s | 554 MB | 386 MB |

All measured append and replay budgets pass. LARGE is manual/dedicated and remains outside PR CI.

Package, GovernedEvidence and lifecycle lookup distributions plus 1,000-record local benchmark normalization are retained in `evaluation/performance/lookups.json`.

## Release composition

`docs/BETA_RELEASE_INVENTORY.json` classifies every changed or untracked path. Generated operational evidence is retained for review but must be published as immutable CI artifacts; build metadata and local files are excluded. No commit, tag, push or merge occurred.
