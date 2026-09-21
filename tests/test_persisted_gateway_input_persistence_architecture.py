from pathlib import Path
ROOT=Path(__file__).parents[1]
def test_persisted_record_is_metadata_only_and_gateway_has_no_owner_repository_dependency():
    domain=(ROOT/"jmoraIs/gateway_input.py").read_text();persistence=(ROOT/"jmoraIs/infrastructure/persisted_gateway_input.py").read_text();gateway=(ROOT/"jmoraIs/llm_gateway/application.py").read_text()
    record=domain[domain.index("class PersistedGatewayInputRecord"):domain.index("class PersistedGatewayInputQueryPort")]
    for forbidden in ("dto: object","MedicalDocument","defense:AuditDefense","ClinicalReasoningInput","prompt","output_text"):assert forbidden not in record
    for forbidden in ("MedicalDocumentRepository","AuditDefenseRepository","OrthopedicAssessmentRepository","evaluation") :assert forbidden not in gateway
    assert "persisted_inputs.persist" in gateway and "persisted_gateway_input_id" in gateway
    assert "raw secret" not in persistence.lower() and "latest(" not in persistence
def test_migration_has_rls_append_only_fk_and_no_destructive_legacy_backfill():
    source=(ROOT/"alembic/versions/043_persisted_gateway_inputs.py").read_text()
    for required in ("ENABLE ROW LEVEL SECURITY","append_only","NOBYPASSRLS" if False else "REVOKE UPDATE,DELETE","persisted_gateway_input_id","llm_invocations"):assert required in source
    assert "UPDATE llm_invocations" not in source and "INSERT INTO persisted_gateway_inputs SELECT" not in source

def test_completeness_anchor_is_atomic_infrastructure_only_and_not_backfilled():
    migration=(ROOT/"alembic/versions/044_persisted_gateway_input_checkpoints.py").read_text()
    replay=(ROOT/"jmoraIs/infrastructure/cryptographic_replay.py").read_text()
    application=(ROOT/"jmoraIs/llm_gateway/application.py").read_text()
    assert "AFTER INSERT ON persisted_gateway_inputs" in migration
    assert "cryptographic_stream_checkpoints" in migration
    assert "INSERT INTO persisted_gateway_inputs" not in migration
    assert "SELECT stream_id FROM cryptographic_stream_checkpoints" in replay
    assert "persisted_gateway_inputs" in replay and "STREAM_COMPLETENESS_FAILURE" in replay
    assert "cryptographic_stream_checkpoints" not in application
    assert "UPDATE cryptographic_stream_checkpoints" not in replay
    assert "INSERT INTO cryptographic_stream_checkpoints" not in replay
    assert "evaluation" not in replay
