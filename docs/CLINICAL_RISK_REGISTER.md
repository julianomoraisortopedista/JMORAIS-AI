# Clinical Risk Register

| Risk | Control | Residual limitation |
|---|---|---|
| Fabricated citation | Authoritative verification and EvidencePackage boundary | Benchmark scale insufficient |
| Retracted evidence | Append-only lifecycle and live validity | Update cadence needs operations policy |
| Tampered history | DB controls, hash chain, replay and alerts | No keyed signatures |
| Unsafe recommendation | Appraisal, explainability, human review | No prospective clinical validation |
| Unauthorized review | Persistent identity, policy and audit | Production IAM absent |
| Tenant crossover | Tenant/organization identity | RLS not implemented |
| Backup corruption | Isolated restore plus replay | Retention is deployment-specific |

Any integrity alert, unauthorized review, `TAMPERED` replay or benchmark-threshold breach blocks promotion.
