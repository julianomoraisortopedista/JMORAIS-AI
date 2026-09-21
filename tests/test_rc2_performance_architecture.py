from pathlib import Path

from evaluation.performance.rc2_benchmark import percentiles

ROOT = Path(__file__).resolve().parents[1]


def test_percentiles_are_deterministic_and_include_tail_and_max():
    assert percentiles([5, 1, 4, 2, 3]) == {"p50": 3, "p90": 5, "p95": 5, "p99": 5, "max": 5}


def test_performance_tooling_never_enters_production_dependencies():
    for path in (ROOT / "jmoraIs").rglob("*.py"):
        assert "evaluation.performance" not in path.read_text(), path
    source = (ROOT / "evaluation/performance/rc2_benchmark.py").read_text()
    assert "tests." not in source
    assert "latest(" not in source and "SET row_security = off" not in source


def test_regression_budgets_are_generous_and_security_preserving():
    budgets = (ROOT / "evaluation/performance/rc2-budgets.json").read_text()
    assert '"minimum_success_rate": 1.0' in budgets
    assert '"maximum_retained_growth_bytes"' in budgets
    assert '"replay_integrity": "VALID"' in budgets
