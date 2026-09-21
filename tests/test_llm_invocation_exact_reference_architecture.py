from pathlib import Path

from jmoraIs.llm_gateway.exact_reference import PersistedLLMInvocationReference


def test_gateway_owner_defines_single_metadata_only_invocation_reference():
    definitions = [path for path in Path("jmoraIs").rglob("*.py") if "class PersistedLLMInvocationReference" in path.read_text()]
    assert definitions == [Path("jmoraIs/llm_gateway/exact_reference.py")]
    assert not {"output_text", "prompt", "raw_response", "provider_payload", "clinical_payload"}.intersection(
        PersistedLLMInvocationReference.__annotations__
    )


def test_exact_adapter_has_no_scalar_fallback_or_non_owner_dependency():
    source = Path("jmoraIs/llm_gateway/exact_reference_persistence.py").read_text()
    assert ".latest(" not in source and ".history(" not in source
    assert "clinical_workspace" not in source and "evaluation" not in source
    assert "def reference_for" in source and "def get_exact" in source
    migration = Path("alembic/versions/055_llm_invocation_exact_reference.py").read_text()
    assert 'sa.Column("output_text"' not in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "append_only" in migration


def test_draft_reference_requires_typed_invocation_reference():
    source = Path("jmoraIs/governed_llm_draft/exact_reference.py").read_text()
    persistence = Path("jmoraIs/governed_llm_draft/exact_reference_persistence.py").read_text()
    assert "invocation_reference: PersistedLLMInvocationReference" in source
    assert "LEGACY_MISSING_PERSISTED_LLM_INVOCATION_REFERENCE" in persistence
