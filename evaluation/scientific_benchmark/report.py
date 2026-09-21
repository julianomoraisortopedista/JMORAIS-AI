from __future__ import annotations

import json
from dataclasses import asdict

from .models import BenchmarkReport


def render_json(report: BenchmarkReport) -> str:
    return json.dumps(asdict(report), ensure_ascii=False, indent=2, sort_keys=True)


def render_markdown(report: BenchmarkReport) -> str:
    metrics = report.metrics
    lines = [
        f"# Scientific benchmark {report.dataset_version}", "",
        f"Generated: {report.generated_at}", "",
        "| Record | Match | Vancouver | Confidence | Duplicate |", "|---|---:|---:|---:|---|",
    ]
    for item in report.results:
        lines.append(f"| {item.record_id} | {item.predicted_match} | {item.vancouver_valid} | "
                     f"{item.reconciliation.confidence:.4f} | {item.duplicate_of or ''} |")
    lines.extend(["", f"Precision: {metrics.precision:.4f}", f"Recall: {metrics.recall:.4f}",
                  f"False positive rate: {metrics.false_positive_rate:.4f}",
                  f"False negative rate: {metrics.false_negative_rate:.4f}", "", "## Coverage", ""])
    lines.extend(f"- {source}: {coverage:.4f}" for source, coverage in metrics.coverage.items())
    return "\n".join(lines) + "\n"
