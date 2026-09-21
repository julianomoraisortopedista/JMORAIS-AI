from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def test_harness_is_validation_only_and_contains_no_clinical_policy():
    source=(ROOT/"evaluation/e2e_acceptance/harness.py").read_text()
    assert "jmoraIs" not in source and "diagnos" not in source.lower() and "treatment" not in source.lower()
    production="\n".join(x.read_text() for x in (ROOT/"jmoraIs/api").glob("*.py"))
    assert "e2e_acceptance" not in production
