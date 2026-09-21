from pathlib import Path
ROOT=Path(__file__).parents[1]

def test_link_is_reference_only_without_false_reasoning_dependency():
    domain=(ROOT/"jmoraIs/audit_defense/domain.py").read_text()
    application=(ROOT/"jmoraIs/audit_defense/application.py").read_text()
    adapter=(ROOT/"jmoraIs/audit_defense/document_traceability.py").read_text()
    assert "MedicalDocumentVersionReference" in domain and "sections" not in domain
    assert "medical_documents" not in application and "document.sections" not in application
    assert "MedicalDocumentJsonCodec" in adapter and "latest(" not in adapter
    assert "evaluation" not in domain+application+adapter
    assert "SELECT " not in application and "sqlalchemy" not in domain+application

def test_migration_preserves_rls_append_only_and_exact_version_fk():
    migration=(ROOT/"alembic/versions/042_stage11_stage12_traceability.py").read_text()
    assert "stage11_document_version" in migration and "medical_document_versions" in migration
    assert '["stage11_document_stream_id","stage11_document_version"]' in migration
    assert '["document_stream_id","version"]' in migration
    assert "DROP POLICY" not in migration and "DISABLE ROW LEVEL SECURITY" not in migration

def test_e2e_stage12_manifest_uses_final_linked_package():
    source=(ROOT/"evaluation/e2e_acceptance/adapters.py").read_text()
    block=source[source.index("class TraceableAuditDefenseStageAdapter"):]
    assert "self._documents.get_exact(reference)" in block
    assert "link_stage11_document" in block and "artifact.stage11_document_reference" in block
    assert "self._repository.get_exact(reference)" in block
    assert "history(" not in block and "latest(" not in block
    assert "generated.stream_id" not in block
    assert ".latest(" not in block[block.index("def reread"):block.index("def describe",block.index("def reread"))]
