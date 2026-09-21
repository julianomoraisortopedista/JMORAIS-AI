from pathlib import Path


ROOT = Path("jmoraIs/smart_fhir")


def test_smart_boundary_has_no_network_clinical_or_persistence_bypass():
    source = "\n".join(path.read_text() for path in ROOT.glob("*.py"))
    forbidden = ("requests", "httpx", "urllib.request", "pubmed", "crossref",
                 "patient_context", "clinical_state", "EvidencePackage", "ClinicalIngestionService")
    assert not any(value in source for value in forbidden)
    assert "jwt.encode" not in source


def test_smart_boundary_does_not_persist_tokens_or_define_clinical_authorization():
    infrastructure = (ROOT / "infrastructure.py").read_text()
    application = (ROOT / "application.py").read_text()
    assert "access_token" not in infrastructure and "refresh_token" not in infrastructure
    assert "authorized_operations" not in application
    assert "PostgreSQLIdentitySecurityAudit" not in infrastructure
