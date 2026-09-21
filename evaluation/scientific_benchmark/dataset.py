from __future__ import annotations

import json
from pathlib import Path

from .models import BenchmarkRecord, SourceObservation


class BenchmarkDatasetError(ValueError):
    pass


class BenchmarkDatasetLoader:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path(__file__).with_name("data") / "authoritative_v1.json"

    def load(self) -> tuple[str, tuple[BenchmarkRecord, ...]]:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != 1 or not payload.get("dataset_version"):
            raise BenchmarkDatasetError("unsupported or unversioned benchmark dataset")
        records = []
        for item in payload.get("records", []):
            observations = tuple(
                SourceObservation(
                    source=source["source"],
                    source_url=source["source_url"],
                    retrieved_at=source["retrieved_at"],
                    title=source.get("title"), journal=source.get("journal"),
                    year=source.get("year"), pmid=source.get("pmid"),
                    pmcid=source.get("pmcid"), doi=source.get("doi"),
                    authors=tuple(source.get("authors", [])), raw=source.get("raw", {}),
                ) for source in item["observations"]
            )
            records.append(BenchmarkRecord(
                record_id=item["record_id"], pmid=item["pmid"], pmcid=item.get("pmcid"),
                doi=item["doi"], title=item["title"], journal=item["journal"],
                year=item["year"], authors=tuple(item["authors"]),
                vancouver=item["vancouver"], observations=observations,
                case_type=item.get("case_type", "REAL_AUTHORITATIVE_CASE"),
                study_design=item.get("study_design", "UNCLASSIFIED"),
                publication_status=item.get("publication_status", "CURRENT"),
                language=item.get("language", "und"),
                expected_existence_status=item.get("expected_existence_status", "EXISTS"),
                expected_metadata_status=item.get("expected_metadata_status", "AUTHORITATIVE"),
                expected_reconciliation_status=item.get("expected_reconciliation_status", "MATCH"),
                expected_vancouver_eligibility=item.get("expected_vancouver_eligibility", True),
                expected_verification_result=item.get("expected_verification_result", "VERIFIED"),
                benchmark_rationale=item.get("benchmark_rationale", "Confirmed by authoritative sources"),
                last_verified_at=item.get("last_verified_at", payload.get("retrieved_at", "")),
            ))
        if not records:
            raise BenchmarkDatasetError("benchmark dataset is empty")
        return payload["dataset_version"], tuple(records)
