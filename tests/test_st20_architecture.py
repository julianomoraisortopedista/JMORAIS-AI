from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_postgresql_is_confined_to_infrastructure_and_persistence_adapters():
    for relative in (
        "jmoraIs/scientific_domain.py", "jmoraIs/evidence_ledger.py",
        "jmoraIs/appraisal/domain.py", "jmoraIs/appraisal/governed.py",
        "jmoraIs/clinical/governed.py", "jmoraIs/clinical/review_governance.py",
        "jmoraIs/application/ports.py",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8").lower()
        assert "postgres" not in source
        assert "sqlalchemy" not in source


def test_production_modules_do_not_create_schema_shortcuts():
    for path in (ROOT / "jmoraIs").rglob("*.py"):
        assert "metadata.create_all" not in path.read_text(encoding="utf-8")


def test_persistent_history_repositories_expose_no_destructive_methods():
    from jmoraIs.appraisal.persistence import SQLAlchemyGovernedEvidenceRepository
    from jmoraIs.clinical.governance_persistence import (
        SQLAlchemyConflictAdjudicationRepository,
        SQLAlchemyGovernedDecisionAuditRepository,
        SQLAlchemyGovernedEvidenceLifecycleRepository,
    )
    for repository in (
        SQLAlchemyGovernedEvidenceRepository,
        SQLAlchemyConflictAdjudicationRepository,
        SQLAlchemyGovernedDecisionAuditRepository,
        SQLAlchemyGovernedEvidenceLifecycleRepository,
    ):
        assert not hasattr(repository, "update")
        assert not hasattr(repository, "delete")
