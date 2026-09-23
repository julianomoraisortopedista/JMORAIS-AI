import re
from pathlib import Path
from jmoraIs.appraisal.exact_reference import PersistedGovernedEvidenceReference

def test_governed_evidence_owner_defines_metadata_only_exact_reference():
    definitions=[path for path in Path("jmoraIs").rglob("*.py") if re.search(r"class PersistedGovernedEvidenceReference\s*[:(]", path.read_text())]
    assert definitions==[Path("jmoraIs/appraisal/exact_reference.py")]
    assert not {"payload","scientific_payload","appraisal_payload"}.intersection(PersistedGovernedEvidenceReference.__annotations__)

def test_exact_reference_has_no_workspace_evaluation_or_scalar_fallback_dependency():
    source=(Path("jmoraIs/appraisal/exact_reference_persistence.py").read_text())
    assert "clinical_workspace" not in source and "evaluation" not in source
    assert ".latest(" not in source and ".history(" not in source.replace("self._lifecycle.history(","")
    assert "def get_exact" in source and "def reference_for" in source
