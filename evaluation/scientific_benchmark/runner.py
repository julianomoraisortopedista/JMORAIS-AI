from __future__ import annotations

from datetime import datetime, timezone

from .metrics import calculate_metrics
from .models import BenchmarkRecord, BenchmarkReport, RecordResult
from .validation import find_duplicates, reconcile, valid_doi, valid_pmcid, valid_pmid, validate_vancouver


class BenchmarkRunner:
    def run(self, dataset_version: str, records: tuple[BenchmarkRecord, ...]) -> BenchmarkReport:
        duplicates = find_duplicates(records)
        results = []
        for record in records:
            identifiers_valid = valid_pmid(record.pmid) and valid_pmcid(record.pmcid) and valid_doi(record.doi)
            reconciliation = reconcile(record)
            vancouver_valid = validate_vancouver(record)
            results.append(RecordResult(
                record_id=record.record_id,
                predicted_match=identifiers_valid and reconciliation.matched and vancouver_valid,
                expected_match=record.expected_reconciliation_status == "MATCH",
                identifiers_valid=identifiers_valid,
                duplicate_of=duplicates.get(record.record_id),
                vancouver_valid=vancouver_valid,
                reconciliation=reconciliation,
            ))
        result_tuple = tuple(results)
        return BenchmarkReport(dataset_version, datetime.now(timezone.utc).isoformat(), result_tuple,
                               calculate_metrics(result_tuple))
