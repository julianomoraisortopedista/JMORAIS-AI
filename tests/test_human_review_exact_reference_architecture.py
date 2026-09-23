import re
from pathlib import Path
from jmoraIs.llm_human_review.exact_reference import PersistedHumanReviewReference
def test_human_review_owns_single_metadata_only_exact_reference():
    definitions=[p for p in Path("jmoraIs").rglob("*.py") if re.search(r"class PersistedHumanReviewReference\s*[:(]", p.read_text())]
    assert definitions==[Path("jmoraIs/llm_human_review/exact_reference.py")]
    assert not {"draft_content","clinical_payload","prompt","llm_response","jwt","jti"}.intersection(PersistedHumanReviewReference.__annotations__)
def test_exact_path_has_no_history_current_state_workspace_or_evaluation():
    source=Path("jmoraIs/llm_human_review/exact_reference_persistence.py").read_text()
    assert ".history(" not in source and ".current_state(" not in source and ".latest(" not in source
    assert "clinical_workspace" not in source and "evaluation" not in source
    assert "def reference_for" in source and "def get_exact" in source
