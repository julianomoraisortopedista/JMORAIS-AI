from pathlib import Path

from jmoraIs.governed_llm_draft.exact_reference import PersistedGovernedLLMDraftReference


def test_governed_draft_owner_defines_metadata_only_exact_reference():
    definitions = [
        path for path in Path("jmoraIs").rglob("*.py")
        if "class PersistedGovernedLLMDraftReference" in path.read_text()
    ]
    assert definitions == [Path("jmoraIs/governed_llm_draft/exact_reference.py")]
    assert not {"reviewable_content", "prompt", "raw_response", "provider_payload", "clinical_payload"}.intersection(
        PersistedGovernedLLMDraftReference.__annotations__
    )


def test_exact_resolution_has_no_workspace_evaluation_or_scalar_fallback():
    source = Path("jmoraIs/governed_llm_draft/exact_reference_persistence.py").read_text()
    assert "clinical_workspace" not in source and "evaluation" not in source
    assert ".latest(" not in source and ".history(" not in source
    assert "def reference_for" in source and "def get_exact" in source
    migration = Path("alembic/versions/054_governed_llm_draft_exact_reference.py").read_text()
    assert 'sa.Column("reviewable_content",' not in migration


def test_frozen_contexts_do_not_depend_on_workspace_or_exact_reference_adapter():
    for root in ("jmoraIs/llm_gateway", "jmoraIs/llm_human_review", "jmoraIs/medical_documents"):
        for path in Path(root).rglob("*.py"):
            content = path.read_text()
            assert "clinical_workspace" not in content
            # Approved persistence adapters compose exact upstream persistence.
            if path.name != "exact_reference_persistence.py":
                assert "exact_reference_persistence" not in content
