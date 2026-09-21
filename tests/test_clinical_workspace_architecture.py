"""No workspace commands, persistence, discovery, decision engine or LLM."""
import ast
from pathlib import Path

from jmoraIs.clinical_workspace.viewers import (
    ClinicalSummaryView, ClinicalWorkspaceView, EvidenceView, ExplainabilityView,
)
from jmoraIs.clinical_workspace.remaining import TimelineView, MedicalDocumentView, HumanReviewView, AuditDefenseView


def test_read_only_boundary_and_source_hygiene():
    root = Path("jmoraIs/clinical_workspace")
    for path in root.glob("*.py"):
        source = path.read_text()
        assert all(line.rstrip() == line and "\t" not in line for line in source.splitlines())
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not any(part in (node.module or "").split(".") for part in
                    ("persistence", "infrastructure", "sqlalchemy", "llm_gateway", "application"))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr in {"get_exact", "get_timeline_exact", "clinical_summary", "evidence", "explainability", "medical_document"}
            assert not isinstance(node, (ast.Try, ast.AsyncFunctionDef))
        assert not any(isinstance(node, ast.FunctionDef) and node.name in
            {"append", "persist", "save", "update", "delete", "reference_for", "generate", "evaluate"}
            for node in ast.walk(tree))
    for model in (ClinicalSummaryView, ClinicalWorkspaceView, EvidenceView, ExplainabilityView,
                  TimelineView, MedicalDocumentView, HumanReviewView, AuditDefenseView):
        assert model.__dataclass_params__.frozen
