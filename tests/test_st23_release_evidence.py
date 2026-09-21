import json
from pathlib import Path
from evaluation.scientific_benchmark.dataset import BenchmarkDatasetLoader


def test_governed_authoritative_dataset_meets_minimum_scale_and_separates_negatives():
    payload=json.loads(Path("evaluation/scientific_benchmark/data/authoritative_v1.json").read_text())
    version, records=BenchmarkDatasetLoader().load()
    assert version == "authoritative-biomedical-v2.0.0"
    assert len(records) >= 100
    assert len(payload["negative_cases"]) >= 20
    assert all(item["case_type"] == "REAL_AUTHORITATIVE_CASE" for item in payload["records"])
    assert all(item["case_type"] == "SYNTHETIC_NEGATIVE_TEST_CASE" for item in payload["negative_cases"])
    assert all(item["last_verified_at"] and item["authoritative_sources_used"] for item in payload["records"])


def test_dataset_diversity_floors_are_machine_checked():
    payload=json.loads(Path("evaluation/scientific_benchmark/data/authoritative_v1.json").read_text())
    records=payload["records"]
    assert len({item["journal"] for item in records}) >= 20
    assert len({item["study_design"] for item in records}) >= 6
    assert sum(item["publication_status"] == "RETRACTED" for item in records) >= 10
    assert sum(item["publication_status"] == "CORRECTED" for item in records) >= 10
    required={"case_id","expected_existence_status","expected_metadata_status",
              "expected_reconciliation_status","expected_vancouver_eligibility",
              "expected_verification_result","benchmark_rationale","last_verified_at"}
    assert all(required <= item.keys() for item in records)


def test_performance_profiles_are_deterministic_and_separate_from_pr_ci():
    profiles=json.loads(Path("evaluation/performance/profiles.json").read_text())["profiles"]
    assert [profiles[name]["events"] for name in ("SMALL","MEDIUM","LARGE")] == [100,10000,100000]
    assert profiles["SMALL"]["ci"] and not profiles["LARGE"]["ci"]
