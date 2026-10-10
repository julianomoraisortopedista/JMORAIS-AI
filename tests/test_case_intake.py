import base64
import json
import time

import pytest
from fastapi.testclient import TestClient

from jmoraIs.application.case_intake import (
    CaseIntakeRejected, CaseExtractionService, case_intake_prompt, extract_text, prepare_documents,
)
from jmoraIs.application.deidentification import DeidentificationRejected, PatientIdentifiers, deidentify
from jmoraIs.llm_gateway import CanonicalLLMGateway, LLMProvider, MockProviderAdapter, PromptGovernanceService
from jmoraIs.llm_gateway.infrastructure import (
    InMemoryInvocationRepository, InMemoryLLMInvocationContextRepository, InMemoryPromptAuditRepository,
    InMemoryPromptRepository,
)
from jmoraIs.tenancy.context import TenantContextBinder
from jmoraIs.tenancy.domain import TenantContext
from jmoraIs.workbench.app import create_app
from tests.test_llm_gateway import model, response
from tests.test_scientific_justification import NOW, Crossref
from tests.test_workbench import H, TOKEN, SearchablePubMed

SYNTHETIC_TAX_ID = "123.456" + ".789-09"  # synthetic test value
IDS = PatientIdentifiers(name="José Carlos da Silva", cpf=SYNTHETIC_TAX_ID, card_number="0123456789012345-6",
                         birth_date="03/04/1962", phone="(11) 98765-4321", email="jose@exemplo.com")
LAUDO = """Paciente: JOSÉ CARLOS DA SILVA   Idade: 64 anos
Data de nascimento: 03/04/1962
Carteirinha: 0 123 456789012345-6   CPF 12345678909   RG: 12.345.678-9
Tel (11) 98765-4321  jose@exemplo.com  Endereço: Rua A, 1  CEP 01234-567
Nome da mãe: Maria Aparecida
CNS 700 0000 0000 0000
Data do exame: 12/08/2026
Achados: Condropatia grau IV no compartimento femorotibial medial.
Conclusão: Osteoartrose avançada. Sr. Jose relata dor há 3 anos; joseense é outra palavra."""


def test_deidentification_removes_identifiers_and_keeps_clinical_content():
    out = deidentify(LAUDO, IDS)
    for leaked in ("JOSÉ", "Jose", "SILVA", "12345678909", "456789012345", "98765", "jose@", "Rua A", "01234-567",
                   "Maria Aparecida", "03/04/1962", "700 0000", "12.345.678"):
        assert leaked not in out.text, leaked
    for kept in ("Idade: 64 anos", "Data do exame: 12/08/2026", "Condropatia grau IV", "dor há 3 anos", "joseense"):
        assert kept in out.text, kept
    assert out.removed["NOME"] >= 2 and "CPF" in out.removed


def test_surviving_identifier_blocks_the_text():
    from jmoraIs.application.deidentification import _assert_clean
    ids = PatientIdentifiers(name="Ana Paula", cpf=SYNTHETIC_TAX_ID, email="a@b.com")
    for leaked in ("Ana com dor", "cpf 12345678909", "contato a@b.com"):
        with pytest.raises(DeidentificationRejected):
            _assert_clean(leaked, ids, ["Ana", "Paula"])
    assert "Ana" not in deidentify("Ana Paula com dor.", ids).text


def test_text_extraction_accepts_only_text_documents():
    assert extract_text("laudo.txt", "Achados normais".encode()) == "Achados normais"
    for name, content in (("foto.jpg", b"\xff\xd8"), ("rx.png", b"x"), ("laudo.pdf", b"not a pdf")):
        with pytest.raises(CaseIntakeRejected):
            extract_text(name, content)
    with pytest.raises(CaseIntakeRejected):
        prepare_documents([], "história", PatientIdentifiers())  # identifiers required to remove them


def service(output):
    prompts, audit = InMemoryPromptRepository(), InMemoryPromptAuditRepository()
    version = PromptGovernanceService(prompts, audit, clock=lambda: NOW).register(case_intake_prompt(), created_by="t")
    adapter = MockProviderAdapter((response(output_text=output),))
    gateway = CanonicalLLMGateway(prompts, audit, InMemoryInvocationRepository(), InMemoryLLMInvocationContextRepository(),
                                  (adapter,), clock=lambda: NOW)
    return CaseExtractionService(gateway, prompt_version_id=version.prompt_version_id, model=model(LLMProvider.MOCK),
                                 clock=lambda: NOW), adapter


TENANT = TenantContext("t-1", "org-1", "dr", "CLINICIAN", "CLINICAL_DOCUMENTATION", "ST-02", "corr-case-test-0001")


def run_extract(output):
    history, docs = prepare_documents([("laudo.txt", LAUDO.encode())], "José Carlos com dor no joelho direito há 3 anos, EVA 8/10.", IDS)
    svc, adapter = service(output)
    with TenantContextBinder().bind_tenant(TENANT):
        return svc.extract(history, docs), adapter


def test_only_quote_grounded_facts_survive_and_ai_never_sees_identifiers():
    output = json.dumps({"facts": [
        {"category": "ACHADO_IMAGEM", "statement": "Condropatia grau IV medial", "quote": "Condropatia grau IV no compartimento femorotibial medial", "source": "Documento 1"},
        {"category": "ESCALA_FUNCIONAL", "statement": "EVA 8/10", "quote": "EVA 8/10", "source": "Documento 1"},
        {"category": "TRATAMENTO_CONSERVADOR", "statement": "Fisioterapia 6 meses", "quote": "fisioterapia por 6 meses", "source": "História"},
        {"category": "QUEIXA", "statement": "Nome", "quote": "Paciente: [NOME REMOVIDO]", "source": "Documento 1"},
        {"category": "INVALID", "statement": "x", "quote": "x", "source": "x"},
    ], "icd10_suggestions": [{"code": "M17.1", "description": "Gonartrose"}, {"code": "BAD", "description": "x"}]})
    result, adapter = run_extract(output)
    assert [f.statement for f in result.facts] == ["Condropatia grau IV medial", "EVA 8/10"]
    assert result.facts[1].source == "História"  # quote found in history, source corrected
    assert result.discarded == 3 and result.icd10_suggestions == ({"code": "M17.1", "description": "Gonartrose"},)
    payload = adapter.requests[0].canonical_payload
    for leaked in ("JOSÉ", "José", "12345678909", "98765", "jose@exemplo.com"):
        assert leaked not in payload


def test_malformed_or_refused_model_output():
    assert run_extract("não é json")[0].status == "UNGROUNDED"


def test_case_endpoints_full_flow_without_storing_identifiers():
    output = json.dumps({"facts": [{"category": "ACHADO_IMAGEM", "statement": "Condropatia grau IV",
                                    "quote": "Condropatia grau IV no compartimento femorotibial medial", "source": "Documento 1"}],
                         "icd10_suggestions": [{"code": "M17.1", "description": "Gonartrose"}]})
    app = create_app(pubmed=SearchablePubMed(), crossref=Crossref(), clock=lambda: NOW, token=TOKEN,
                     resolve_case_extractor=lambda: (lambda: service(output)[0]))
    c = TestClient(app, base_url="http://127.0.0.1:8770")
    ids = {"name": "José Carlos da Silva", "cpf": "123.456.789-09", "card_number": "0123456789012345-6"}
    assert c.post("/api/case", headers=H, json={"history": "x", "identifiers": ids, "consent": False}).status_code == 400
    case = c.post("/api/case", headers=H, json={"history": "José com dor no joelho.", "identifiers": ids, "consent": True}).json()
    assert "José" not in case["history"]
    doc = {"name": "laudo.txt", "content_base64": base64.b64encode(LAUDO.encode()).decode(), "identifiers": ids}
    view = c.post(f"/api/case/{case['case_id']}/document", headers=H, json=doc).json()
    assert "JOSÉ" not in view["documents"][0]["text"] and view["documents"][0]["removed"]["NOME"] >= 1
    assert c.post(f"/api/case/{case['case_id']}/document", headers=H,
                  json={**doc, "name": "rx.jpg"}).status_code == 400
    c.post(f"/api/case/{case['case_id']}/extract", headers=H)
    for _ in range(50):
        view = c.get(f"/api/case/{case['case_id']}", headers=H).json()
        if view["status"] != "RUNNING":
            break
        time.sleep(0.05)
    assert view["status"] == "PENDING_PHYSICIAN_REVIEW" and len(view["facts"]) == 1
    fid = view["facts"][0]["fact_id"]
    assert c.post(f"/api/case/{case['case_id']}/confirm", headers=H, json={"fact_ids": ["forged"]}).status_code == 400
    assert c.post(f"/api/case/{case['case_id']}/confirm", headers=H, json={"fact_ids": [fid], "icd10": ["M17-1"]}).status_code == 400
    confirmed = c.post(f"/api/case/{case['case_id']}/confirm", headers=H,
                       json={"fact_ids": [fid], "edits": {fid: "Condropatia grau IV medial (RM)"}, "icd10": ["m17.1"]}).json()["confirmed"]
    assert confirmed["icd10"] == ["M17.1"] and confirmed["facts"][0]["edited"] is True
    assert "José" not in json.dumps(c.get(f"/api/case/{case['case_id']}", headers=H).json())
    doc = c.post("/api/document", headers=H, json={
        "claim": "Total knee replacement improves pain versus nonsurgical care", "procedure": "Artroplastia total do joelho",
        "rol": "SIM", "case_id": case["case_id"], "laterality": "Direito", "regime": "Internação",
        "tuss": [{"code": "30726034", "description": "Artroplastia total de joelho"}],
        "opme": [{"description": "Prótese total de joelho", "anvisa": "80000000000", "quantity": 1}]})
    html = doc.json()["html"]
    assert doc.status_code == 200 and "30726034" in html and "M17.1" in html and "Prótese total de joelho" in html
    assert "Condropatia grau IV medial (RM)" in html and 'data-ident="paciente"' in html and "José" not in html
    bad_tuss = c.post("/api/document", headers=H, json={"claim": "Total knee replacement improves pain", "procedure": "ATJ",
                                                        "tuss": [{"code": "123"}]})
    assert bad_tuss.status_code == 422
    assert c.delete(f"/api/case/{case['case_id']}", headers=H).status_code == 200
    assert c.get(f"/api/case/{case['case_id']}", headers=H).status_code == 404


def test_extraction_requires_configured_model():
    c = TestClient(create_app(pubmed=SearchablePubMed(), crossref=Crossref(), token=TOKEN), base_url="http://127.0.0.1:8770")
    case = c.post("/api/case", headers=H, json={"history": "dor", "identifiers": {"name": "Fulano"}, "consent": True}).json()
    assert c.post(f"/api/case/{case['case_id']}/extract", headers=H).status_code == 503


def test_identifiers_are_detected_locally_from_labelled_lines():
    from jmoraIs.application.deidentification import detect_identifiers
    found = detect_identifiers(LAUDO)
    assert found["name"] == "JOSÉ CARLOS DA SILVA" and found["birth_date"] == "03/04/1962"
    assert found["cpf"] == "12345678909" and found["card_number"].endswith("456789012345-6")
    assert found["email"] == "jose@exemplo.com" and found["phone"] == "(11) 98765-4321"
    # invalid CPF checksum, non-name values and clinical text are not taken as identifiers
    assert detect_identifiers("Nome: 123\nCPF: 111.111.111-11\nCondropatia grau IV.") == {}
    # detected values, once confirmed, de-identify the document completely
    ids = PatientIdentifiers(name=found["name"], cpf=found["cpf"], card_number=found["card_number"])
    assert "SILVA" not in deidentify(LAUDO, ids).text


def test_scan_endpoint_reads_identifiers_without_ai_or_storage():
    def no_ai():
        raise AssertionError("scan must not call the model")
    c = TestClient(create_app(pubmed=SearchablePubMed(), crossref=Crossref(), token=TOKEN, resolve_case_extractor=no_ai),
                   base_url="http://127.0.0.1:8770")
    doc = {"name": "laudo.txt", "content_base64": base64.b64encode(LAUDO.encode()).decode()}
    assert c.post("/api/case/scan", json=doc).status_code in (401, 403)
    found = c.post("/api/case/scan", headers=H, json=doc).json()["identifiers"]
    assert found["name"] == "JOSÉ CARLOS DA SILVA"
    assert c.post("/api/case/scan", headers=H, json={**doc, "name": "rx.jpg"}).status_code == 400


def test_prose_names_and_record_numbers_are_removed_without_being_supplied():
    text = ("PACIENTE: X DATA NASC.: 01/02/1990\nMÉDICO SOLIC.: Dr. Fulano PRONTUÁRIO: 8219652\n"
            "A paciente Raisa Marx Nascimento apresenta dor. Negativa para o paciente Luís Claudio Marchesi, portador "
            "de gonartrose. Sra. Maria da Silva relata melhora. O paciente apresenta EVA 8.")
    out = deidentify(text).text
    for leaked in ("Raisa", "Marchesi", "Luís", "Maria da Silva", "8219652"):
        assert leaked not in out
    assert "O paciente apresenta EVA 8." in out and "gonartrose" in out
    from jmoraIs.application.deidentification import detect_identifiers
    assert detect_identifiers("A paciente Raisa Marx Nascimento apresenta dor.")["name"] == "Raisa Marx Nascimento"
    assert detect_identifiers(deidentify("Endereço: Rua A, 10   Tel x").text) == {}


def test_anvisa_registration_is_kept_but_a_valid_cpf_is_not():
    out = deidentify("Kit EasyBlock - Registro ANVISA nº 81420899005. CPF 123.456.789-09. ANVISA 52998224725").text
    assert "81420899005" in out and "123.456.789-09" not in out and "52998224725" not in out
