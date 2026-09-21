from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_exact_reference_path_has_no_latest_history_or_scalar_fallback():
    source = (ROOT / "jmoraIs/patient_context/exact_reference.py").read_text()
    persistence = (ROOT / "jmoraIs/patient_context/persistence.py").read_text()
    exact = persistence[persistence.index("class PostgreSQLPatientContextExactReferenceRepository"):]
    assert ".latest(" not in source + exact
    assert ".history(" not in source + exact
    assert "evaluation" not in source + exact
    assert "FHIR" not in source + exact


def test_reference_table_is_metadata_only_and_owner_controlled():
    migration = (ROOT / "alembic/versions/051_patient_context_exact_reference.py").read_text()
    for prohibited in ("clinical_text", "fhir_payload", "email", "phone", "national_identifier"):
        assert prohibited not in migration
    assert "ROW LEVEL SECURITY" in migration
    assert "append_only" in migration
    for path in (ROOT / "evaluation").rglob("*.py"):
        assert "PersistedPatientContextReference(" not in path.read_text(), path
