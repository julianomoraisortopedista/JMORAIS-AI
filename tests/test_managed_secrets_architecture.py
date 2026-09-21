from pathlib import Path

ROOT=Path(__file__).parents[1]
def source(path):return (ROOT/path).read_text()

def test_secret_domain_and_ports_do_not_import_provider_sdks_or_environment_details():
    combined=source("jmoraIs/secrets/domain.py")+source("jmoraIs/secrets/ports.py")
    for forbidden in ("boto3","azure","google.cloud","hvac","os.environ","dotenv","pathlib"):
        assert forbidden not in combined.lower()

def test_secret_models_and_audit_have_no_raw_value_field():
    combined=source("jmoraIs/secrets/domain.py")+source("alembic/versions/023_managed_secrets_keys.py")
    assert "raw_secret" not in combined and "secret_value" not in combined
    assert 'sa.Column("value"' not in combined and 'sa.Column("payload"' not in combined

def test_homologation_rejects_development_provider_and_has_no_database_url_use():
    composition=source("jmoraIs/api/homologation.py")
    assert "homologation_safe" in composition and "development secret providers are prohibited" in composition
    assert "config.database_url" not in composition and "SecretBackedDatabaseEngine" in composition

def test_pseudonymization_adapter_uses_key_port_not_raw_hmac_bytes():
    patient=source("jmoraIs/patient_context/infrastructure.py")
    assert "self._secret" not in patient and "hmac.new" not in patient
    assert "self._keys.pseudonymize" in patient
