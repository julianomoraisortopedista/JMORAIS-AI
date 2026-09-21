import ast
from dataclasses import fields
from pathlib import Path
from jmoraIs.reasoning_input.domain import ClinicalReasoningInput,EvidencePackageReference
from jmoraIs.reasoning_input.ports import ClinicalReasoningInputQueryPort,ClinicalReasoningInputRepository
ROOT=Path("jmoraIs/reasoning_input")
def test_contract_has_no_dependency_on_source_domain_entities_or_engines():
    forbidden=("jmoraIs.patient_context","jmoraIs.clinical_state","jmoraIs.application","jmoraIs.appraisal","jmoraIs.connect","jmoraIs.clinical")
    for path in ROOT.glob("*.py"):
        allowed={"jmoraIs.clinical_state.exact_reference":{"PersistedClinicalStateReference"},
                 "jmoraIs.appraisal.exact_reference":{"PersistedGovernedEvidenceReference"}}
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node,ast.ImportFrom) and (node.module or "").startswith(forbidden):
                assert node.module in allowed and {alias.name for alias in node.names}<=allowed[node.module],path
def test_only_reference_fields_cross_the_boundary():
    names={item.name for item in fields(ClinicalReasoningInput)}
    assert "patient_clinical_state" in names and "evidence_packages" in names
    assert set(item.name for item in fields(EvidencePackageReference))=={"reference_id","origin","author","recorded_at","policy_version"}
    source=(ROOT/"domain.py").read_text().lower()
    for forbidden in ("patientidentity","laboratoryresult","imagingstudy","scientificarticle","claim_evidence_relationships"):
        assert forbidden not in source
def test_repository_and_query_ports_are_protocols():
    assert ClinicalReasoningInputRepository._is_protocol and ClinicalReasoningInputQueryPort._is_protocol
