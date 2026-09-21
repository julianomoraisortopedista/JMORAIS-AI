from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SourceObservation:
    source: str
    source_url: str
    retrieved_at: str
    title: str | None = None
    journal: str | None = None
    year: int | None = None
    pmid: str | None = None
    pmcid: str | None = None
    doi: str | None = None
    authors: tuple[str, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict, compare=False)


@dataclass(frozen=True)
class BenchmarkRecord:
    record_id: str
    pmid: str
    pmcid: str | None
    doi: str
    title: str
    journal: str
    year: int
    authors: tuple[str, ...]
    vancouver: str
    observations: tuple[SourceObservation, ...]
    case_type: str = "REAL_AUTHORITATIVE_CASE"
    study_design: str = "UNCLASSIFIED"
    publication_status: str = "CURRENT"
    language: str = "und"
    expected_existence_status: str = "EXISTS"
    expected_metadata_status: str = "AUTHORITATIVE"
    expected_reconciliation_status: str = "MATCH"
    expected_vancouver_eligibility: bool = True
    expected_verification_result: str = "VERIFIED"
    benchmark_rationale: str = "Confirmed by authoritative sources"
    last_verified_at: str = ""


@dataclass(frozen=True)
class ReconciliationResult:
    matched: bool
    field_agreement: dict[str, bool]
    conflicts: dict[str, tuple[str, ...]]
    source_coverage: tuple[str, ...]
    confidence: float


@dataclass(frozen=True)
class RecordResult:
    record_id: str
    predicted_match: bool
    expected_match: bool
    identifiers_valid: bool
    duplicate_of: str | None
    vancouver_valid: bool
    reconciliation: ReconciliationResult


@dataclass(frozen=True)
class BenchmarkMetrics:
    true_positive: int
    true_negative: int
    false_positive: int
    false_negative: int
    precision: float
    recall: float
    false_positive_rate: float
    false_negative_rate: float
    coverage: dict[str, float]


@dataclass(frozen=True)
class BenchmarkReport:
    dataset_version: str
    generated_at: str
    results: tuple[RecordResult, ...]
    metrics: BenchmarkMetrics
