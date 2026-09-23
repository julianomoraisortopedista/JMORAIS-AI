import re
from pathlib import Path

from jmoraIs.clinical_state.exact_reference import (
    PersistedClinicalStateReference, PersistedClinicalStateTimelineReference,
)


def test_exact_reference_boundary_is_owned_by_clinical_state_without_workspace_or_fhir_dependency():
    root = Path("jmoraIs/clinical_state")
    source = "\n".join(path.read_text() for path in root.glob("*.py"))
    assert "jmoraIs.fhir" not in source
    assert "clinical_workspace" not in source
    exact = (root / "exact_reference_persistence.py").read_text()
    assert ".latest(" not in exact and ".history(" not in exact and ".at(" not in exact
    prohibited = {"payload", "clinical_payload", "fhir_payload", "document", "free_text"}
    assert not prohibited.intersection(PersistedClinicalStateReference.__annotations__)
    assert not prohibited.intersection(PersistedClinicalStateTimelineReference.__annotations__)


def test_only_clinical_state_defines_its_trusted_reference_types():
    definitions = []
    for path in Path("jmoraIs").rglob("*.py"):
        text = path.read_text()
        if re.search(r"class (?:PersistedClinicalStateReference|PersistedClinicalStateTimelineReference)\s*[:(]", text):
            definitions.append(path)
    assert definitions == [Path("jmoraIs/clinical_state/exact_reference.py")]
