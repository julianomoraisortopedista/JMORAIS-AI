from __future__ import annotations

import argparse
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from evaluation.scientific_benchmark.dataset import BenchmarkDatasetLoader
from evaluation.scientific_benchmark.runner import BenchmarkRunner
from evaluation.scientific_benchmark.sources import AuthoritativeClients
from evaluation.scientific_benchmark.validation import normalize_doi, normalize_text


def run(output: Path, *, enforce_beta: bool) -> int:
    version, records = BenchmarkDatasetLoader().load()
    timeout = float(os.getenv("BENCHMARK_TIMEOUT_SECONDS", "20"))
    delay = float(os.getenv("BENCHMARK_DELAY_SECONDS", "0.4"))
    clients = AuthoritativeClients(timeout=timeout)
    calls = {name: {"attempted": 0, "resolved": 0, "failures": []}
             for name in ("pubmed", "pmc", "crossref", "openalex", "semantic_scholar")}

    tasks = []
    for record in records:
        requests = (("pubmed", record.pmid), ("crossref", record.doi),
                    ("openalex", record.doi))
        if record.pmcid:
            requests += (("pmc", record.pmcid),)
        requests += (("semantic_scholar", record.doi),)
        for source, identifier in requests:
            calls[source]["attempted"] += 1
            tasks.append((record, source, identifier))

    def verify(task):
        record, source, identifier = task
        try:
            result = getattr(clients, source)(identifier)
            if source == "pubmed":
                ids = {item["idtype"]: item["value"] for item in result["articleids"]}
                matched = normalize_doi(ids.get("doi")) == normalize_doi(record.doi)
            elif source == "pmc": matched = str(result.get("pmid")) == record.pmid
            elif source == "crossref": matched = normalize_doi(result.get("DOI")) == normalize_doi(record.doi)
            else: matched = normalize_text(result.get("title")) == normalize_text(record.title)
            reason = None if matched else "metadata_mismatch"
        except Exception as exc:
            matched, reason = False, type(exc).__name__
        time.sleep(delay)
        return source, record.record_id, matched, reason

    workers = int(os.getenv("BENCHMARK_WORKERS", "8"))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for source, record_id, matched, reason in pool.map(verify, tasks):
            if matched: calls[source]["resolved"] += 1
            else: calls[source]["failures"].append({"record_id": record_id, "reason": reason})

    static = BenchmarkRunner().run(version, records)
    for values in calls.values():
        values["failure_rate"] = 1 - values["resolved"] / values["attempted"] if values["attempted"] else 1.0
    authoritative = tuple(name for name in calls if name != "semantic_scholar")
    authoritative_attempted = sum(calls[name]["attempted"] for name in authoritative)
    authoritative_resolved = sum(calls[name]["resolved"] for name in authoritative)
    report = {
        "dataset_version": version, "dataset_size": len(records), "sources": calls,
        "precision": static.metrics.precision, "recall": static.metrics.recall,
        "false_positive_rate": static.metrics.false_positive_rate,
        "false_negative_rate": static.metrics.false_negative_rate,
        "coverage": static.metrics.coverage,
        "identifier_resolution_success": authoritative_resolved / max(authoritative_attempted, 1),
        "metadata_reconciliation_agreement": authoritative_resolved / max(authoritative_attempted, 1),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    if enforce_beta:
        accepted = (
            len(records) >= 100 and report["precision"] >= 0.98
            and report["recall"] >= 0.95 and report["false_positive_rate"] <= 0.01
            and report["identifier_resolution_success"] >= 0.90
            and report["metadata_reconciliation_agreement"] >= 0.90
            and all(calls[name]["failure_rate"] <= 0.20 for name in authoritative)
        )
        return 0 if accepted else 2
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--enforce-beta-thresholds", action="store_true")
    args = parser.parse_args()
    raise SystemExit(run(args.output, enforce_beta=args.enforce_beta_thresholds))
