from __future__ import annotations

import ast
from pathlib import Path

from jmoraIs.appraisal.governed import GovernedEvidenceRepository
from jmoraIs.appraisal.persistence import SQLAlchemyGovernedEvidenceRepository
from jmoraIs.clinical.governance_persistence import (
    SQLAlchemyConflictAdjudicationRepository,
    SQLAlchemyGovernedDecisionAuditRepository,
    SQLAlchemyGovernedEvidenceLifecycleRepository,
)


ROOT = Path(__file__).resolve().parents[1] / "jmoraIs"


def test_application_ports_expose_no_destructive_operations():
    for contract in (GovernedEvidenceRepository,):
        assert "update" not in contract.__dict__
        assert "delete" not in contract.__dict__
    for adapter in (SQLAlchemyGovernedEvidenceRepository,
                    SQLAlchemyConflictAdjudicationRepository,
                    SQLAlchemyGovernedDecisionAuditRepository,
                    SQLAlchemyGovernedEvidenceLifecycleRepository):
        assert not hasattr(adapter, "update")
        assert not hasattr(adapter, "delete")


def test_domain_and_application_do_not_import_persistence_adapters():
    for relative in ("appraisal/governed.py", "clinical/governed.py", "clinical/review_governance.py"):
        source = (ROOT / relative).read_text(encoding="utf-8")
        tree = ast.parse(source)
        modules = [node.module for node in ast.walk(tree)
                   if isinstance(node, ast.ImportFrom) and node.module]
        assert not any("persistence" in module or "infrastructure" in module for module in modules)


def test_persistence_adapters_have_no_scientific_connector_dependency():
    for relative in ("appraisal/persistence.py", "clinical/governance_persistence.py"):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "jmoraIs.connect" not in source
        assert "services.pubmed" not in source
