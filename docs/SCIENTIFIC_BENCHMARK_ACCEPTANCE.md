# Scientific Benchmark Acceptance — ALPHA to BETA

## Required dataset composition

The BETA benchmark must be versioned, independently reviewable and contain at least:

| Dimension | Minimum |
|---|---:|
| Total publication/identifier cases | 100 |
| Authoritative source families per eligible record | 3 |
| Source families represented overall | 4 |
| Distinct journals/publishers | 20 |
| Study-design categories | 6 |
| Retracted publications | 10 |
| Corrected publications | 10 |
| Malformed/nonexistent/negative identifier cases | 20 |
| Metadata-conflict cases | 15 |
| Languages | 2 |

At least PubMed, PMC where applicable, Crossref and OpenAlex must be represented.
Semantic Scholar is measured when available but does not block a record solely due
to service unavailability. Study-design diversity must include systematic review or
meta-analysis, randomized trial, cohort, case-control, case series/report and
guideline or another governed evidence source.

The minima balance meaningful diversity with a dataset that can be manually curated
and revalidated during BETA. They are acceptance floors, not statistical claims of
clinical performance.

## Metric thresholds

| Metric | BETA threshold | Rationale |
|---|---:|---|
| Identifier/citation precision | ≥ 0.98 | False trust is more dangerous than withholding a record. |
| Recall | ≥ 0.95 | Allows bounded upstream outages while requiring high valid-record recovery. |
| False-positive rate | ≤ 0.01 | Incorrectly verified identifiers must be exceptional. |
| False-negative rate | ≤ 0.05 | Mirrors the recall floor. |
| Unresolved reconciliation rate | ≤ 0.10 | Conflicts remain fail-closed but excessive unresolved records make the system unusable. |
| Identifier resolution success | ≥ 0.90 | Accounts for transient source failures without hiding systemic outages. |
| Per-source operational failure rate | ≤ 0.20 | A degraded source must be visible and investigated. |
| Eligible records with required provenance | 1.00 | Provenance is a non-negotiable trust invariant. |

Metrics must be reported overall and per source. Confidence scoring never overrides
an identifier, provenance or reconciliation failure.

## Release rule

BETA requires all composition and metric thresholds in one frozen dataset version,
two consecutive live runs without an unexplained regression, and human review of
every false positive, false negative, retracted/corrected case and metadata conflict.
The current three-record dataset does not satisfy BETA composition and must not be
used to claim benchmark acceptance.
