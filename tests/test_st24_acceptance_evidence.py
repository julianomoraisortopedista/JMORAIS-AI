import json
from pathlib import Path

def load(path): return json.loads(Path(path).read_text())

def test_authoritative_reconciliation_is_persisted_or_unavailability_documented():
    data=load("evaluation/scientific_benchmark/data/authoritative_v1.json")
    eligible=[item for item in data["records"] if item["publication_status"]=="CURRENT"]
    for item in eligible:
        sources=set(item["authoritative_sources_used"])
        assert {"PubMed","Crossref","OpenAlex"} <= sources or item["source_unavailability"]
        assert len(item["observations"]) >= 2

def test_real_governed_conflict_cases_exceed_acceptance_floor():
    conflicts=load("evaluation/scientific_benchmark/data/authoritative_v1.json")["conflict_cases"]
    assert len(conflicts) >= 15
    assert all(item["case_type"]=="REAL_AUTHORITATIVE_CONFLICT_CASE" for item in conflicts)
    assert all(item["expected_resolution"] and item["authoritative_sources_used"] for item in conflicts)

def test_representative_restore_is_equivalent_and_nonempty():
    report=load("evaluation/release_evidence/representative-restore-replay.json")
    assert report["backup"]==report["restore"]==report["replay"]=="VALID"
    assert report["state_equivalent"] and report["streams"] >= 7 and report["verified_events"] > 0
    assert all(report["table_counts"].values())

def test_all_performance_profiles_are_valid_and_within_replay_append_budgets():
    expected={"small":100,"medium":10000,"large":100000}
    for profile,count in expected.items():
        result=load(f"evaluation/performance/{profile}.json")
        assert result["event_count"]==count
        assert result["integrity"]==result["full_replay_integrity"]=="VALID"
        assert result["append_ms"]["p95"] < 500
        assert result["full_replay_seconds"] < 15
        assert result["append_throughput_events_s"] > 0

def test_every_worktree_path_has_release_classification():
    inventory=load("docs/BETA_RELEASE_INVENTORY.json")
    assert inventory["items"]
    assert all(item["classification"] in {"INCLUDE","EXCLUDE","GENERATED","LOCAL_ONLY"} for item in inventory["items"])
