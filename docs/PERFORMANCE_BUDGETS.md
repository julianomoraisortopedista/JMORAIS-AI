# Performance Budgets

| Operation | Dataset | Beta budget |
|---|---:|---:|
| Single-stream replay | 1,000 events | p95 < 3 s |
| Full replay | 10,000 events | < 15 s |
| Event append | one event | p95 < 500 ms |
| Package lookup/integrity | one package | p95 < 250 ms |
| Local benchmark normalization | 1,000 citations | < 30 s |

External latency is reported separately. A breach blocks promotion pending investigation; budgets must not be relaxed merely to pass CI.
