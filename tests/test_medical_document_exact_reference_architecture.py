from pathlib import Path
from jmoraIs.medical_documents.exact_reference import PersistedMedicalDocumentVersionReference
def test_medical_documents_owns_single_metadata_only_reference():
    definitions=[p for p in Path("jmoraIs").rglob("*.py") if "class PersistedMedicalDocumentVersionReference" in p.read_text()]
    assert definitions==[Path("jmoraIs/medical_documents/exact_reference.py")]
    assert not {"sections","content","document","clinical_payload"}.intersection(PersistedMedicalDocumentVersionReference.__annotations__)
def test_exact_path_has_no_history_latest_workspace_or_evaluation():
    source=Path("jmoraIs/medical_documents/exact_reference_persistence.py").read_text()
    assert ".history(" not in source and ".latest(" not in source
    assert "clinical_workspace" not in source and "evaluation" not in source
    assert "def reference_for" in source and "def get_exact" in source
def test_legacy_stage_11_12_trace_adapter_remains_unchanged():
    source=Path("jmoraIs/audit_defense/document_traceability.py").read_text()
    assert "class PostgreSQLMedicalDocumentTraceAdapter" in source and "def reference_exact" in source
