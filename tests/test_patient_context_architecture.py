import ast
from dataclasses import FrozenInstanceError
from pathlib import Path
import pytest
from jmoraIs.patient_context.infrastructure import PatientContextDocument
from jmoraIs.patient_context.persistence import PatientContextJsonCodec
from tests.test_patient_context_domain import context

ROOT=Path("jmoraIs/patient_context")
def test_bounded_context_does_not_depend_on_frozen_phase_one_modules():
    forbidden=("jmoraIs.application","jmoraIs.appraisal","jmoraIs.clinical","jmoraIs.evidence_ledger","jmoraIs.infrastructure","jmoraIs.verification")
    for path in ROOT.glob("*.py"):
        tree=ast.parse(path.read_text())
        imports=[node.module or "" for node in ast.walk(tree) if isinstance(node,ast.ImportFrom)]
        assert not any(module.startswith(forbidden) for module in imports),path

def test_domain_and_ports_do_not_import_infrastructure():
    for name in ("domain.py","ports.py","privacy.py","privacy_ports.py","application.py","ingestion.py"):
        assert "patient_context.infrastructure" not in (ROOT/name).read_text()

def test_postgresql_document_contract_is_immutable_and_versioned():
    from datetime import datetime,timezone
    document=PatientContextDocument("context","patient",1,None,datetime.now(timezone.utc),{"schema_version":1})
    with pytest.raises(FrozenInstanceError): document.version=2
    assert document.payload["schema_version"]==1

def test_patient_context_contains_no_reasoning_dependencies_or_terms():
    source="\n".join(path.read_text() for path in ROOT.glob("*.py"))
    for forbidden in ("EvidencePackage","PubMed","Crossref","LLM","embedding","treatment_recommendation"):
        assert forbidden not in source

def test_only_canonical_ingestion_application_appends_patient_context():
    for path in ROOT.glob("*.py"):
        if path.name in {"ingestion.py","infrastructure.py","persistence.py"}: continue
        assert "._repository.append(" not in path.read_text(),path

def test_direct_identifiers_do_not_leak_into_scientific_domain():
    source=Path("jmoraIs/scientific_domain.py").read_text().lower()
    for forbidden in ("full_name","national_id","street_address","patientidentity"):
        assert forbidden not in source

def test_postgresql_document_codec_round_trips_complete_immutable_aggregate():
    original=context()
    assert PatientContextJsonCodec().decode(PatientContextJsonCodec().encode(original))==original

def test_authorized_ingestion_is_the_only_atomic_stage1_write_boundary():
    ingestion=(ROOT/"ingestion.py").read_text()
    assert "ClinicalIngestionService" in ingestion and ".append_atomic(" in ingestion
    assert "self._repository.append(" not in ingestion
    assert "DirectPatientContextWriteProhibited" in (ROOT/"application.py").read_text()

def test_authorized_ingestion_record_is_metadata_only_and_has_no_reasoning_dependencies():
    from dataclasses import fields
    from jmoraIs.patient_context.privacy import AuthorizedClinicalIngestionRecord
    names={field.name for field in fields(AuthorizedClinicalIngestionRecord)}
    assert {"ingestion_record_id","patient_context_id","patient_context_version","integrity_hash"} <= names
    assert not names.intersection({"clinical_payload","problems","medications","exams","findings","notes","imaging"})
    source="\n".join((ROOT/name).read_text() for name in ("privacy.py","ingestion.py","privacy_ports.py"))
    for forbidden in ("PubMed","Crossref","LLMProvider","RAG","evaluation.e2e_acceptance"):
        assert forbidden not in source

def test_stage1_and_stage2_e2e_adapters_are_distinct_and_do_not_write_twice():
    source=Path("evaluation/e2e_acceptance/adapters.py").read_text()
    assert "class AuthorizedIngestionPersistenceAdapter" in source
    assert "class PatientContextRereadStageAdapter" in source
    stage1=source[source.index("class AuthorizedIngestionPersistenceAdapter"):source.index("class PatientContextRereadStageAdapter")]
    stage2=source[source.index("class PatientContextRereadStageAdapter"):]
    assert ".append(" not in stage1 and ".append(" not in stage2
