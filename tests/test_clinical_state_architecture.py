import ast
from pathlib import Path
from jmoraIs.clinical_state.ports import PatientContextQueryPort,ClinicalStateRepository,ClinicalStateAuditPort

ROOT=Path("jmoraIs/clinical_state")
def test_dependency_direction_and_forbidden_capabilities():
    forbidden=("jmoraIs.connect","jmoraIs.application","jmoraIs.evidence_ledger","jmoraIs.clinical")
    for path in ROOT.glob("*.py"):
        imports=[node.module or "" for node in ast.walk(ast.parse(path.read_text())) if isinstance(node,ast.ImportFrom)]
        assert not any(module.startswith(forbidden) for module in imports),path
    source="\n".join(path.read_text().lower() for path in ROOT.glob("*.py"))
    for term in ("pubmed","crossref","evidencepackage","embedding","language_model","treatment recommendation","surgical indication"):
        assert term not in source
def test_required_ports_are_explicit_protocols():
    assert all(hasattr(item,"__protocol_attrs__") or getattr(item,"_is_protocol",False) for item in (PatientContextQueryPort,ClinicalStateRepository,ClinicalStateAuditPort))
def test_clinical_state_contains_no_direct_identity_fields():
    source=(ROOT/"domain.py").read_text().lower()
    for term in ("full_name","national_id","email","phone","street_address"):
        assert term not in source
