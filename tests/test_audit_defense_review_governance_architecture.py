from pathlib import Path

ROOT=Path(__file__).parents[1]


def test_human_review_remains_generic_and_owner_adapter_uses_exact_reference_path():
    application=(ROOT/"jmoraIs/llm_human_review/application.py").read_text()
    adapter=(ROOT/"jmoraIs/audit_defense/review_governance.py").read_text()
    assert "UpstreamReviewGovernancePort" not in application or "self._upstream" in application
    assert "PostgreSQLAuditDefenseRepository" not in application
    assert "audit_defense" not in application
    assert "reference_from_upstream(reference)" in adapter
    assert "get_exact(persisted_reference)" in adapter
    assert "latest(" not in adapter and ".history(" not in adapter
    assert "evaluation" not in adapter and "tests" not in adapter


def test_router_preserves_medical_document_and_audit_defense_dispatch_without_repository_branching():
    router=(ROOT/"jmoraIs/llm_human_review/upstream.py").read_text()
    assert "class MedicalDocumentReviewGovernanceAdapter" in router
    assert "class UpstreamReviewGovernanceRouter" in router
    assert "artifact_type" in router
    assert "PostgreSQLAuditDefenseRepository" not in router
    stage14=(ROOT/"tests/test_llm_human_review_postgresql.py").read_text()
    assert 'UpstreamReviewGovernanceRouter({"AuditDefense":audit_governance})' in stage14
    service_block=stage14[stage14.index("service = AuthorizedLLMHumanReviewService"):]
    assert "upstream_governance" in service_block and "Upstream()" not in service_block
