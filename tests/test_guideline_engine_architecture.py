import ast
from pathlib import Path
from jmoraIs.guideline_engine.ports import GuidelineQueryPort,RecommendationAuditPort,RecommendationRepository
ROOT=Path("jmoraIs/guideline_engine")
def test_dependency_direction_and_no_connectors_or_model_stack():
    forbidden=("jmoraIs.patient_context","jmoraIs.clinical_state","jmoraIs.application","jmoraIs.connect","jmoraIs.embeddings")
    for path in ROOT.glob("*.py"):
        imports=[node.module or "" for node in ast.walk(ast.parse(path.read_text())) if isinstance(node,ast.ImportFrom)]
        assert not any(module.startswith(forbidden) for module in imports),path
    source="\n".join(path.read_text().lower() for path in ROOT.glob("*.py"))
    for term in ("pubmed","crossref","openalex","language_model","vector_store","autonomous_prescribing","diagnosis_engine"):
        assert term not in source
def test_ports_are_protocols_and_canonical_strength_is_reused():
    assert GuidelineQueryPort._is_protocol and RecommendationRepository._is_protocol and RecommendationAuditPort._is_protocol
    source=(ROOT/"domain.py").read_text()
    assert "from jmoraIs.appraisal.domain import RecommendationStrength" in source
    assert "class RecommendationStrength" not in source

def test_persistent_source_respects_dependency_inversion_and_shared_classification():
    application=(ROOT/"source_application.py").read_text().lower()
    persistence=(ROOT/"source_persistence.py").read_text()
    ports=(ROOT/"ports.py").read_text()
    assert "sqlalchemy" not in application and "postgres" not in application
    assert "class GuidelineQueryPort" in ports and "class GuidelineRepository" in ports
    assert "PostgreSQLGuidelineSourceRepository" in persistence
    assert "tenant_id" not in persistence and "PatientContext" not in persistence
