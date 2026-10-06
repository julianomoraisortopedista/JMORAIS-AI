import base64
from datetime import timedelta
import json
import os

import pytest
from fastapi.testclient import TestClient

from jmoraIs.application.report_style import ReportStyleRejected, ReportStyleStore, deidentify_model
from jmoraIs.application.request_intake import RequestIntakeRejected, RequestIntakeService, request_prompt
from jmoraIs.application.surgical_catalog import CatalogStore, starter_templates
from jmoraIs.llm_gateway import CanonicalLLMGateway, LLMProvider, MockProviderAdapter, PromptGovernanceService
from jmoraIs.llm_gateway.infrastructure import (
    InMemoryInvocationRepository, InMemoryLLMInvocationContextRepository, InMemoryPromptAuditRepository,
    InMemoryPromptRepository,
)
from jmoraIs.tenancy.context import TenantContextBinder
from jmoraIs.workbench.app import create_app
from tests.test_case_intake import SYNTHETIC_TAX_ID
from tests.test_llm_gateway import model, response
from tests.test_report_drafting import FACTS, TENANT, draft
from tests.test_scientific_justification import NOW, Crossref
from tests.test_workbench import H, TOKEN, SearchablePubMed

MODEL_REPORT = f"""RELATÓRIO MÉDICO
Paciente: Maria Helena Duarte   Idade: 70 anos
CPF: {SYNTHETIC_TAX_ID}
Carteirinha: 0099 8877 6655
A paciente Maria Helena refere gonalgia à direita há 4 anos, refratária a tratamento conservador.
Ao exame: varo de 10 graus, flexo de 15 graus.
Solicito artroplastia total do joelho direito e os materiais abaixo.
"""


def intake_service(output):
    prompts, audit = InMemoryPromptRepository(), InMemoryPromptAuditRepository()
    version = PromptGovernanceService(prompts, audit, clock=lambda: NOW).register(request_prompt(), created_by="t")
    adapter = MockProviderAdapter((response(output_text=json.dumps(output)),))
    gateway = CanonicalLLMGateway(prompts, audit, InMemoryInvocationRepository(), InMemoryLLMInvocationContextRepository(),
                                  (adapter,), clock=lambda: NOW)
    return RequestIntakeService(gateway, prompt_version_id=version.prompt_version_id, model=model(LLMProvider.MOCK), clock=lambda: NOW), adapter


PARSED = {"template_id": "tpl-artroplastia-total-do-joelho-c", "procedure": "ATJ direita", "laterality": "Direito",
          "supplier": "Zimmer Biomet", "hospital": "Hospital Santa Cruz", "date": (NOW.date() + timedelta(days=14)).isoformat(),
          "time": "7h", "duration_minutes": 150, "regime": "Internação", "anesthesia": "Raquianestesia",
          "icu": True, "blood_reserve": None, "notes": "Arco em C"}


def test_report_model_is_deidentified_and_rejects_short_text():
    cleaned = deidentify_model(MODEL_REPORT)
    for leaked in ("Maria", "Helena", "Duarte", "123.456", "0099 8877"):
        assert leaked not in cleaned.text, leaked
    assert "varo de 10 graus" in cleaned.text and "Solicito artroplastia" in cleaned.text
    with pytest.raises(ReportStyleRejected):
        deidentify_model("Paciente: Ana Souza")


def test_style_store_saves_only_cleaned_text_with_private_permissions(tmp_path):
    store = ReportStyleStore(tmp_path / "style.json")
    assert store.load() is None
    saved = store.save("Modelo editado pelo médico. Contato " + "fulano@exemplo.com" + ". História clínica: ... Exame físico: ...")
    assert "fulano@" not in saved and store.load() == saved
    assert oct(os.stat(tmp_path / "style.json").st_mode & 0o777) == "0o600"
    store.delete()
    assert store.load() is None


def test_report_follows_model_titles_and_order_but_never_cites_it():
    output = {"sections": [
        {"section": "indicacao", "title": "CONDUTA", "sentences": [{"text": "Indicada artroplastia.", "fact_ids": ["CTX"]}]},
        {"section": "historia", "title": "HISTÓRIA", "sentences": [
            {"text": "Dor EVA 8/10.", "fact_ids": ["F1"]},
            {"text": "Varo de 10 graus.", "fact_ids": ["MODELO"]}]}], "gaps": []}
    from tests.test_report_drafting import service
    svc, adapter = service(output)
    with TenantContextBinder().bind_tenant(TENANT):
        result = svc.draft(FACTS, "Procedimento: ATJ", "HISTÓRIA ... CONDUTA ...")
    assert [t for _, t, _ in result.sections][:2] == ["CONDUTA", "HISTÓRIA"]
    assert result.dropped == 1  # a sentence sourced from the model is discarded
    assert "MODELO" in json.loads(adapter.requests[0].canonical_payload).__repr__()
    plain, _ = draft({"sections": [{"section": "historia", "title": "X", "sentences": []}], "gaps": []})
    assert plain.sections[0][1] == "História clínica"  # without a model the standard titles stay


def test_request_intake_keeps_only_catalog_choices_and_valid_schedule():
    svc, adapter = intake_service(PARSED)
    with TenantContextBinder().bind_tenant(TENANT):
        result = svc.parse(f"ATJ direita para a paciente CPF {SYNTHETIC_TAX_ID}, Zimmer, Santa Cruz dia 20 às 7h",
                           [("tpl-artroplastia-total-do-joelho-c", "Artroplastia total do joelho")], ["Zimmer Biomet", "Amplitude"])
    assert SYNTHETIC_TAX_ID not in adapter.requests[0].canonical_payload
    assert result.template_id == "tpl-artroplastia-total-do-joelho-c" and result.supplier == "Zimmer Biomet"
    assert result.time == "07:00" and result.date == PARSED["date"] and result.icu is True and result.blood_reserve is None
    forged = dict(PARSED, template_id="tpl-inventado", supplier="Outra", date="2001-01-01", time="25:99", laterality="Ambos",
                  duration_minutes=99999)
    svc, _ = intake_service(forged)
    with TenantContextBinder().bind_tenant(TENANT):
        result = svc.parse("ATJ direita", [("tpl-artroplastia-total-do-joelho-c", "ATJ")], ["Zimmer Biomet"])
    assert (result.template_id, result.supplier, result.date, result.time, result.laterality, result.duration_minutes) == ("", "", "", "", "", 0)
    with pytest.raises(RequestIntakeRejected):
        svc.parse("oi", [], [])


def test_style_and_request_endpoints(tmp_path):
    catalog = CatalogStore(tmp_path / "procedures.json")
    catalog.seed(starter_templates())
    app = create_app(pubmed=SearchablePubMed(), crossref=Crossref(), clock=lambda: NOW, token=TOKEN, catalog=catalog,
                     report_style=ReportStyleStore(tmp_path / "style.json"),
                     resolve_request_parser=lambda: (lambda: intake_service(PARSED)[0]))
    c = TestClient(app, base_url="http://127.0.0.1:8770")
    assert c.get("/api/report-style", headers=H).json() == {"text": None}
    doc = {"name": "modelo.txt", "content_base64": base64.b64encode(MODEL_REPORT.encode()).decode()}
    preview = c.post("/api/report-style/preview", headers=H, json=doc).json()
    assert "Maria" not in preview["text"] and c.get("/api/report-style", headers=H).json() == {"text": None}  # not stored
    assert c.put("/api/report-style", headers=H, json={"text": preview["text"], "confirmed": False}).status_code == 400
    assert c.put("/api/report-style", headers=H, json={"text": preview["text"], "confirmed": True}).status_code == 200
    assert c.get("/api/report-style", headers=H).json()["text"] == preview["text"]
    assert c.delete("/api/report-style", headers=H).json() == {"text": None}
    parsed = c.post("/api/request/parse", headers=H, json={"text": "ATJ direita Zimmer Santa Cruz"}).json()
    assert parsed["template_name"] == "Artroplastia total do joelho com implantes" and parsed["time"] == "07:00"
    assert c.post("/api/request/parse", json={"text": "ATJ direita"}).status_code in (401, 403)
    no_ai = TestClient(create_app(pubmed=SearchablePubMed(), crossref=Crossref(), token=TOKEN), base_url="http://127.0.0.1:8770")
    assert no_ai.post("/api/request/parse", headers=H, json={"text": "ATJ direita"}).status_code == 503


def test_schedule_is_rendered_in_the_request_and_validated():
    c = TestClient(create_app(pubmed=SearchablePubMed(), crossref=Crossref(), clock=lambda: NOW, token=TOKEN),
                   base_url="http://127.0.0.1:8770")
    body = {"claim": "Total knee replacement improves pain versus nonsurgical care", "procedure": "Artroplastia total do joelho",
            "schedule": {"hospital": "Hospital Santa Cruz", "date": "2026-10-20", "time": "07:00", "duration_minutes": 150,
                         "anesthesia": "Raquianestesia", "icu": True, "blood_reserve": False, "supplier": "Zimmer Biomet"}}
    html = c.post("/api/document", headers=H, json=body).json()["html"]
    for expected in ("Agendamento cirúrgico", "Hospital Santa Cruz", "20/10/2026 às 07:00", "150 min", "Reserva de UTI:</td><td>Sim",
                     "Reserva de sangue:</td><td>Não", 'data-ident="cpf"', 'data-ident="nascimento"'):
        assert expected in html, expected
    bad = dict(body, schedule=dict(body["schedule"], time="7h"))
    assert c.post("/api/document", headers=H, json=bad).status_code == 400
