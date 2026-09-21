from __future__ import annotations

from collections import Counter

from .models import BenchmarkMetrics, RecordResult


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def calculate_metrics(results: tuple[RecordResult, ...]) -> BenchmarkMetrics:
    tp = sum(item.predicted_match and item.expected_match for item in results)
    tn = sum(not item.predicted_match and not item.expected_match for item in results)
    fp = sum(item.predicted_match and not item.expected_match for item in results)
    fn = sum(not item.predicted_match and item.expected_match for item in results)
    counts = Counter(source for item in results for source in item.reconciliation.source_coverage)
    total = len(results)
    coverage = {source: _ratio(count, total) for source, count in sorted(counts.items())}
    return BenchmarkMetrics(tp, tn, fp, fn, _ratio(tp, tp + fp), _ratio(tp, tp + fn),
                            _ratio(fp, fp + tn), _ratio(fn, fn + tp), coverage)
