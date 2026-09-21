from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    values = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            values.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            values.append(node.module)
    return tuple(values)


def test_clinical_governed_pipeline_depends_on_appraisal_contract_not_infrastructure():
    modules = imports(ROOT / "jmoraIs/clinical/governed.py")
    assert "jmoraIs.appraisal.governed" in modules
    assert not any("infrastructure" in module for module in modules)


def test_governed_pipeline_has_no_scientific_connector_or_raw_result_access():
    modules = imports(ROOT / "jmoraIs/clinical/governed.py")
    forbidden = ("jmoraIs.connect", "jmoraIs.verification", "jmoraIs.evidence_ledger", "services.pubmed")
    assert not any(module.startswith(forbidden) for module in modules)
    source = (ROOT / "jmoraIs/clinical/governed.py").read_text(encoding="utf-8")
    assert "EligibleEvidenceResult" not in source
    assert "verification_status" not in source


def test_appraisal_boundary_references_package_without_copying_scientific_payload():
    source = (ROOT / "jmoraIs/appraisal/governed.py").read_text(encoding="utf-8")
    assert "evidence_package_id" in source
    assert "publication_identities" not in source
    assert "raw_payload" not in source


def test_public_clinical_service_is_the_governed_pipeline():
    source = (ROOT / "jmoraIs/clinical/__init__.py").read_text(encoding="utf-8")
    assert "ClinicalIntelligenceService = GovernedClinicalIntelligenceService" in source
