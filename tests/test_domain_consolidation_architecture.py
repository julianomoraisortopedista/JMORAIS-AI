from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).parents[1]
PACKAGE = ROOT / "jmoraIs"


def _classes() -> dict[str, list[Path]]:
    definitions: dict[str, list[Path]] = {}
    for path in PACKAGE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                definitions.setdefault(node.name, []).append(path.relative_to(ROOT))
    return definitions


def test_canonical_enums_and_query_port_have_one_definition() -> None:
    definitions = _classes()
    expected = {
        "VerificationStatus": Path("jmoraIs/scientific_domain.py"),
        "SupportDirection": Path("jmoraIs/scientific_domain.py"),
        "EvidenceLevel": Path("jmoraIs/appraisal/domain.py"),
        "RecommendationStrength": Path("jmoraIs/appraisal/domain.py"),
        "ReviewerRole": Path("jmoraIs/clinical/review_governance.py"),
        "EvidencePackageQueryPort": Path("jmoraIs/application/ports.py"),
        "GovernedEvidenceEligibilityGate": Path("jmoraIs/clinical/governed.py"),
        "ReviewAuthorizationPolicy": Path("jmoraIs/clinical/review_governance.py"),
        "AuthorizedRecommendationReviewService": Path("jmoraIs/clinical/review_governance.py"),
    }
    for name, path in expected.items():
        assert definitions[name] == [path]


def test_domain_dataclasses_are_frozen_except_documented_working_aggregates() -> None:
    mutable_exceptions = {
        (Path("jmoraIs/scientific_domain.py"), "ScientificArticle"),
        (Path("jmoraIs/scientific_domain.py"), "SearchRun"),
    }
    found_exceptions: set[tuple[Path, str]] = set()
    for path in PACKAGE.rglob("*.py"):
        relative = path.relative_to(ROOT)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            decorators = [
                item for item in node.decorator_list
                if (isinstance(item, ast.Name) and item.id == "dataclass")
                or (isinstance(item, ast.Call) and isinstance(item.func, ast.Name) and item.func.id == "dataclass")
            ]
            if not decorators:
                continue
            frozen = any(
                isinstance(item, ast.Call)
                and any(
                    keyword.arg == "frozen"
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is True
                    for keyword in item.keywords
                )
                for item in decorators
            )
            identity = (relative, node.name)
            if identity in mutable_exceptions:
                found_exceptions.add(identity)
            else:
                assert frozen, f"domain dataclass must be frozen: {relative}:{node.name}"
    assert found_exceptions == mutable_exceptions


def test_deprecated_clinical_paths_are_tombstones_not_parallel_domains() -> None:
    assert not (PACKAGE / "clinical" / "domain.py").exists()
    assert not (PACKAGE / "clinical" / "infrastructure.py").exists()

    application = (PACKAGE / "clinical" / "application.py").read_text(encoding="utf-8")
    engine = (PACKAGE / "clinical_engine.py").read_text(encoding="utf-8")
    governed = (PACKAGE / "clinical" / "governed.py").read_text(encoding="utf-8")
    assert "DeprecatedClinicalPathError" in application
    assert "DeprecatedClinicalPathError" in engine
    assert "verification_status" not in application
    assert "verification_status" not in engine
    assert "class RecommendationReviewService" in governed
    governed_tree = ast.parse(governed)
    assert "AuthorizedRecommendationReviewService" not in {
        node.name for node in governed_tree.body if isinstance(node, ast.ClassDef)
    }


def test_public_clinical_boundary_exports_only_governed_recommendations() -> None:
    public_boundary = (PACKAGE / "clinical" / "__init__.py").read_text(encoding="utf-8")
    boundary_tree = ast.parse(public_boundary)
    exported_names = {
        element.value
        for node in boundary_tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets)
        and isinstance(node.value, (ast.List, ast.Tuple))
        for element in node.value.elts
        if isinstance(element, ast.Constant) and isinstance(element.value, str)
    }
    assert "ClinicalRecommendation" not in exported_names
    assert "RecommendationConfidence" not in public_boundary
    assert "GovernedClinicalRecommendation" in exported_names
    assert "AuthorizedRecommendationReviewService" in exported_names
