from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JMORAIS = ROOT / "jmoraIs"
FORBIDDEN_PREFIXES = (
    "jmoraIs.connect",
    "services.pubmed",
    "services.crossref",
    "services.scielo",
)


def imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


def test_consumers_cannot_import_scientific_connectors_directly() -> None:
    violations: list[str] = []
    for path in JMORAIS.rglob("*.py"):
        relative = path.relative_to(JMORAIS)
        if relative.parts[0] in {"connect", "application"}:
            continue
        for module in imported_modules(path):
            if module.startswith(FORBIDDEN_PREFIXES):
                violations.append(f"{relative}: {module}")

    assert violations == [], (
        "Scientific connectors may only be composed outside consumer modules; "
        f"use AuthoritativeReconciliationPipeline instead: {violations}"
    )


def test_application_use_case_depends_on_ports_not_concrete_connectors() -> None:
    path = JMORAIS / "application" / "scientific_verification.py"
    imports = imported_modules(path)

    assert not any(module.startswith(FORBIDDEN_PREFIXES) for module in imports)


def test_consumers_cannot_import_low_level_verification_shortcuts() -> None:
    forbidden_names = {
        "verify_article_metadata",
        "verify_publication_authoritatively",
        "decide_publication_verification",
    }
    violations: list[str] = []
    for path in JMORAIS.rglob("*.py"):
        relative = path.relative_to(JMORAIS)
        if relative.parts[0] in {"application", "connect"} or relative.name == "verification.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "jmoraIs.verification":
                imported = {alias.name for alias in node.names}
                bypasses = sorted(imported & forbidden_names)
                if bypasses:
                    violations.append(f"{relative}: {', '.join(bypasses)}")

    assert violations == [], (
        "Consumers must call AuthoritativeReconciliationPipeline, not low-level "
        f"verification functions: {violations}"
    )


def test_external_consumers_cannot_import_scientific_internals() -> None:
    core_modules = {
        "application", "connect", "db", "evidence_ledger", "scientific_domain",
        "scientific_engine", "vancouver", "verification", "infrastructure",
    }
    forbidden = ("jmoraIs.connect", "jmoraIs.evidence_ledger", "jmoraIs.verification")
    violations: list[str] = []
    for path in JMORAIS.rglob("*.py"):
        relative = path.relative_to(JMORAIS)
        top_level = Path(relative.parts[0]).stem
        if top_level in core_modules:
            continue
        for module in imported_modules(path):
            if module.startswith(forbidden):
                violations.append(f"{relative}: {module}")
    assert violations == [], (
        "External modules must consume evidence through ScientificEvidencePackagePort: "
        f"{violations}"
    )


def test_clinical_engine_has_no_status_string_or_internal_result_bypass() -> None:
    source = (JMORAIS / "clinical_engine.py").read_text(encoding="utf-8")
    assert "verification_status" not in source
    assert "EligibleEvidenceResult" not in source


def test_internal_pipeline_is_not_exported_as_public_application_api() -> None:
    source = (JMORAIS / "application" / "__init__.py").read_text(encoding="utf-8")
    assert '"AuthoritativeReconciliationPipeline"' not in source
    assert '"ScientificVerificationInput"' not in source


def test_application_package_port_does_not_depend_on_infrastructure_adapter() -> None:
    imports = imported_modules(JMORAIS / "application" / "evidence_packages.py")
    assert not any(module.startswith("jmoraIs.infrastructure") for module in imports)
