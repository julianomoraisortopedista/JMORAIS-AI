from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def test_frozen_bounded_contexts_do_not_import_fhir():
    frozen=("patient_context","terminology","application","appraisal","clinical_state",
        "reasoning_input","guideline_engine","orthopedic_intelligence","medical_documents",
        "audit_defense","llm_gateway","governed_llm_draft","llm_human_review")
    for name in frozen:
        for path in (ROOT/"jmoraIs"/name).rglob("*.py"):
            assert "jmoraIs.fhir" not in path.read_text() and "from ..fhir" not in path.read_text(),path


def test_fhir_has_no_direct_patient_context_write_or_trust_fallback():
    source="\n".join(path.read_text() for path in (ROOT/"jmoraIs/fhir").glob("*.py"))
    assert "ClinicalIngestionCommand" in source and "_clinical_ingestion.ingest(" in source
    assert "PostgreSQLPatientContextRepository" not in source
    assert "_contexts.append(" not in source
    assert ".latest(" not in source
    assert ".history(" not in source
    assert "evaluation" not in source
    assert "requests." not in source and "httpx" not in source
    assert "raw_payload" not in source and "fhir_payload" not in source
    assert "logging." not in source


def test_fhir_does_not_define_clinical_or_terminology_truth():
    source="\n".join(path.read_text() for path in (ROOT/"jmoraIs/fhir").glob("*.py"))
    for prohibited in ("class PatientContext", "class ClinicalConcept", "class EvidencePackage",
        "class Diagnosis", "class TreatmentRecommendation"):
        assert prohibited not in source
