import ast
from pathlib import Path
from jmoraIs.terminology.ports import (ConceptMappingPort,TerminologyMappingGovernanceQueryPort,
    TerminologyMappingGovernanceRepository,TerminologyQueryPort,TerminologyRepository)
ROOT=Path("jmoraIs/terminology")
def test_terminology_is_architecturally_isolated():
    forbidden=("jmoraIs.patient_context","jmoraIs.clinical_state","jmoraIs.reasoning_input","jmoraIs.application","jmoraIs.appraisal","jmoraIs.clinical","jmoraIs.connect")
    for path in ROOT.glob("*.py"):
        imports=[node.module or "" for node in ast.walk(ast.parse(path.read_text())) if isinstance(node,ast.ImportFrom)]
        assert not any(module.startswith(forbidden) for module in imports),path
def test_ports_preserve_dependency_inversion():
    assert TerminologyRepository._is_protocol and TerminologyQueryPort._is_protocol and ConceptMappingPort._is_protocol
    assert TerminologyMappingGovernanceRepository._is_protocol and TerminologyMappingGovernanceQueryPort._is_protocol
def test_prohibited_capabilities_are_absent():
    source="\n".join(path.read_text().lower() for path in ROOT.glob("*.py"))
    for term in ("evidencepackage","pubmed","crossref","language_model","risk_score","treatment_recommendation","diagnosis_engine"):
        assert term not in source

def test_concept_truth_does_not_duplicate_mapping_governance():
    domain=(ROOT/"domain.py").read_text()
    concept=domain.split("class ClinicalConcept:",1)[1].split("class ConceptMapping:",1)[0]
    assert "mapping_confidence" not in concept and "review_required" not in concept and "policy_version" not in concept
