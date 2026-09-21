from __future__ import annotations

import ast
from pathlib import Path


APPRAISAL = Path(__file__).resolve().parents[1] / "jmoraIs" / "appraisal"


def imported_modules(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return tuple(modules)


def test_appraisal_never_imports_raw_sources_or_scientific_internals():
    forbidden = ("jmoraIs.connect", "jmoraIs.verification", "jmoraIs.evidence_ledger",
                 "services.pubmed", "evaluation")
    violations = []
    for path in APPRAISAL.glob("*.py"):
        violations.extend(
            f"{path.name}: {module}" for module in imported_modules(path)
            if module.startswith(forbidden)
        )
        source = path.read_text(encoding="utf-8")
        assert "EligibleEvidenceResult" not in source
        assert "verification_status" not in source
    assert violations == []


def test_appraisal_domain_has_no_application_or_infrastructure_dependency():
    assert not any(module.startswith("jmoraIs") for module in imported_modules(APPRAISAL / "domain.py"))


def test_appraisal_application_uses_evidence_package_query_protocol():
    source = (APPRAISAL / "application.py").read_text(encoding="utf-8")
    assert "from jmoraIs.application import EvidencePackage, EvidencePackageQueryPort" in source
    assert "jmoraIs.infrastructure" not in source


def test_appraisal_persistence_respects_dependency_inversion():
    ports = (APPRAISAL / "ports.py").read_text(encoding="utf-8")
    application = (APPRAISAL / "application.py").read_text(encoding="utf-8")
    infrastructure = APPRAISAL.parent / "infrastructure" / "appraisal_persistence.py"
    assert "ClinicalAppraisalRepository" in ports
    assert "ClinicalAppraisalQueryPort" in ports
    assert "sqlalchemy" not in application.lower()
    assert "PostgreSQLClinicalAppraisalRepository" in infrastructure.read_text(encoding="utf-8")


def test_governed_boundary_can_resolve_canonical_persisted_appraisal():
    source = (APPRAISAL / "governed.py").read_text(encoding="utf-8")
    assert "issue_persisted" in source
    assert "appraisal_result_id" in source
    assert "clinical_appraisal_records" not in source
