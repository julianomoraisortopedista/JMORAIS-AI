from __future__ import annotations

import ast
from pathlib import Path


CLINICAL = Path(__file__).resolve().parents[1] / "jmoraIs" / "clinical"


def imports(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    result = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.append(node.module)
    return tuple(result)


def test_clinical_intelligence_cannot_import_scientific_connectors_or_raw_results():
    forbidden = ("jmoraIs.connect", "services.pubmed", "services.crossref")
    violations = []
    for path in CLINICAL.glob("*.py"):
        for module in imports(path):
            if module.startswith(forbidden):
                violations.append(f"{path.name}: {module}")
        source = path.read_text(encoding="utf-8")
        assert "EligibleEvidenceResult" not in source
        assert "verification_status" not in source
    assert violations == []


def test_domain_has_no_application_or_infrastructure_dependencies():
    assert not (CLINICAL / "domain.py").exists()
    governed_imports = imports(CLINICAL / "governed.py")
    assert not any("infrastructure" in module for module in governed_imports)


def test_application_depends_on_audit_protocol_not_adapter():
    application_source = (CLINICAL / "application.py").read_text(encoding="utf-8")
    assert "No clinical business rule is retained" in application_source
    assert "raise DeprecatedClinicalPathError" in application_source
