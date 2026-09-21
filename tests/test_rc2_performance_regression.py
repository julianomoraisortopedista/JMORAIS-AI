import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name): return json.loads((ROOT / "evaluation/performance" / name).read_text())


def test_measured_api_database_memory_and_query_plan_budgets():
    report, budgets = load("rc2-baseline.json"), load("rc2-budgets.json")
    api = report["workloads"]["lightweight_authenticated_api"]
    assert all(item["success_rate"] >= budgets["minimum_success_rate"] for item in api.values())
    assert max(item["latency_ms"]["p95"] for item in api.values()) < budgets["authenticated_api_p95_ms"]
    assert report["workloads"]["postgresql_round_trip"]["latency_ms"]["p95"] < budgets["postgresql_round_trip_p95_ms"]
    assert report["memory"]["retained_growth_bytes"] < budgets["maximum_retained_growth_bytes"]
    assert all(plan["Node Type"] == "Index Scan" for plan in report["query_plans"].values())


def test_replay_scaling_is_integrity_valid_and_within_generous_ceiling():
    report, budgets = load("rc2-replay-scaling.json"), load("rc2-budgets.json")
    assert all(item["integrity"] == budgets["replay_integrity"] for item in report["profiles"].values())
    assert report["profiles"]["MEDIUM"]["full_replay_seconds"] < budgets["medium_full_replay_seconds"]
    assert report["profiles"]["LARGE"]["full_replay_seconds"] < budgets["large_full_replay_seconds"]
    assert report["combined_stress_observation"]


def test_every_canonical_workload_has_three_successful_samples():
    workloads = load("rc2-scenarios.json")["workloads"]
    assert len(workloads) == 18
    assert all(item["samples"] == 3 and item["success_rate"] == 1.0 for item in workloads.values())
    assert all(item["scenario_wall_ms"]["p50"] > 0 for item in workloads.values())
