import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_replay_engine_is_read_only_and_infrastructure_only():
    replay = ROOT / "jmoraIs/infrastructure/cryptographic_replay.py"
    source = replay.read_text(encoding="utf-8")
    tree = ast.parse(source)
    methods = {
        node.name for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "update" not in methods
    assert "delete" not in methods
    assert "append" not in methods
    assert "INSERT INTO" not in source
    for path in (
        ROOT / "jmoraIs/scientific_domain.py",
        ROOT / "jmoraIs/evidence_ledger.py",
        ROOT / "jmoraIs/appraisal/domain.py",
        ROOT / "jmoraIs/clinical/governed.py",
    ):
        assert "cryptographic_replay" not in path.read_text(encoding="utf-8")


def test_replay_decision_is_strictly_binary():
    from jmoraIs.infrastructure.cryptographic_replay import ReplayIntegrityStatus
    assert {item.value for item in ReplayIntegrityStatus} == {"VALID", "TAMPERED"}


def test_stage13_and_stage14_critical_streams_are_mandatory_in_global_replay():
    replay = (ROOT / "jmoraIs/infrastructure/cryptographic_replay.py").read_text(encoding="utf-8")
    for table in (
        "governed_llm_draft_lifecycle_events",
        "llm_human_review_events",
        "llm_human_review_security_events",
    ):
        assert table in replay
    assert "_MANDATORY_TRUST_STREAMS" in replay
    assert "mandatory_family:" in replay
    assert "UNVERIFIABLE_STREAM" in replay


def test_stage13_and_stage14_domains_do_not_depend_on_replay_infrastructure():
    for package in ("governed_llm_draft", "llm_human_review"):
        for path in (ROOT / "jmoraIs" / package).glob("*.py"):
            assert "infrastructure.cryptographic_replay" not in path.read_text(encoding="utf-8")
