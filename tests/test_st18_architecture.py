from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return tuple(
        node.module for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    )


def test_trusted_clinical_pipeline_never_imports_raw_scientific_types():
    source = (ROOT / "jmoraIs/clinical/governed.py").read_text(encoding="utf-8")
    assert "EvidencePackage" not in source
    assert "EligibleEvidenceResult" not in source
    assert "verification_status" not in source
    assert "jmoraIs.connect" not in imports(ROOT / "jmoraIs/clinical/governed.py")


def test_lifecycle_port_is_mandatory_for_eligibility_and_service_composition():
    source = (ROOT / "jmoraIs/clinical/governed.py").read_text(encoding="utf-8")
    assert "class GovernedEvidenceLifecycleEligibilityPort(Protocol)" in source
    assert "def __init__(self, lifecycle: GovernedEvidenceLifecycleEligibilityPort)" in source
    assert "gate: GovernedEvidenceEligibilityGate," in source
    assert "gate: GovernedEvidenceEligibilityGate | None" not in source


def test_deprecated_paths_are_fail_closed_tombstones():
    legacy_engine = (ROOT / "jmoraIs/clinical_engine.py").read_text(encoding="utf-8")
    legacy_application = (ROOT / "jmoraIs/clinical/application.py").read_text(encoding="utf-8")
    legacy_review = (ROOT / "jmoraIs/clinical/governed.py").read_text(encoding="utf-8")
    assert "raise DeprecatedClinicalPathError" in legacy_engine
    assert "raise DeprecatedClinicalPathError" in legacy_application
    assert "review without authorization is blocked" in legacy_review


def test_public_contract_does_not_export_legacy_models_or_review():
    source = (ROOT / "jmoraIs/clinical/__init__.py").read_text(encoding="utf-8")
    forbidden = (
        '"FoundationClinicalIntelligenceService"', '"RecommendationReviewService"',
        '"EvidenceAppraisal"', '"RecommendationCandidate"', '"InMemoryDecisionAuditRepository"',
    )
    assert not any(name in source for name in forbidden)
