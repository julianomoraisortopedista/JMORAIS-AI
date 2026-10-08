import base64
import json
import os
import time

import pytest
from fastapi.testclient import TestClient

from jmoraIs.application.appeal_drafting import AppealDraftRejected, AppealDraftingService, appeal_prompt, denial_sentences
from jmoraIs.application.appeal_library import AppealEntry, AppealLibrary, AppealLibraryRejected
from jmoraIs.llm_gateway import CanonicalLLMGateway, LLMProvider, MockProviderAdapter, PromptGovernanceService
from jmoraIs.llm_gateway.infrastructure import (
    InMemoryInvocationRepository, InMemoryLLMInvocationContextRepository, InMemoryPromptAuditRepository,
    InMemoryPromptRepository,
)
from jmoraIs.tenancy.context import TenantContextBinder
from jmoraIs.workbench.app import create_app
from tests.test_case_intake import SYNTHETIC_TAX_ID
from tests.test_llm_gateway import model, response
from tests.test_report_drafting import FACTS, TENANT
from tests.test_scientific_justification import NOW, Crossref
from tests.test_workbench import H, TOKEN, SearchablePubMed

PAST = ("Contestação de negativa de artroplastia total do joelho. A operadora alegou ausência de tratamento "
        "conservador; o relatório comprovou fisioterapia e infiltração. Pedido de reconsideração e junta médica.")
DENIAL = (f"Beneficiária CPF {SYNTHETIC_TAX_ID}. Procedimento negado por ausência de comprovação de tratamento "
          "conservador por 6 meses. Componente patelar não justificado.")


def service(output):
    prompts, audit = InMemoryPromptRepository(), InMemoryPromptAuditRepository()
    version = PromptGovernanceService(prompts, audit, clock=lambda: NOW).register(appeal_prompt(), created_by="t")
    adapter = MockProviderAdapter((response(output_text=json.dumps(output)),))
    gateway = CanonicalLLMGateway(prompts, audit, InMemoryInvocationRepository(), InMemoryLLMInvocationContextRepository(),
                                  (adapter,), clock=lambda: NOW)
    return AppealDraftingService(gateway, prompt_version_id=version.prompt_version_id, model=model(LLMProvider.MOCK), clock=lambda: NOW), adapter


OUTPUT = {"sections": [
    {"section": "sintese", "sentences": [{"text": "A operadora negou por ausência de tratamento conservador por 6 meses.", "source_ids": ["N2"]}]},
    {"section": "clinico", "sentences": [
        {"text": "A paciente fez fisioterapia por 6 meses.", "source_ids": ["F2"]},
        {"text": "Dor EVA 9/10.", "source_ids": ["F1"]},                     # 9 is not in the source: dropped
        {"text": "Conforme a Lei 9.999/2020.", "source_ids": ["L-CDC-ART47"]},  # invented norm number: dropped
        {"text": "Como no caso anterior.", "source_ids": ["EXEMPLO1"]}]},     # examples are not sources: dropped
    {"section": "normativo", "sentences": [{"text": "A interpretação deve favorecer o consumidor (Lei 8.078/1990, art. 47).",
                                            "source_ids": ["L-CDC-ART47"]}]},
    {"section": "pedido", "sentences": [{"text": "Solicito a reconsideração e, se mantida a divergência, junta médica.",
                                         "source_ids": ["L-RN424"]}]}], "gaps": ["Sem laudo de RM anexado."]}


def test_library_requires_clean_text_and_ranks_granted_examples(tmp_path):
    lib = AppealLibrary(tmp_path / "appeals.json")
    granted = lib.add(AppealEntry(kind="NEGATIVA", procedure="Artroplastia total do joelho", outcome="DEFERIDA", text=PAST))
    lib.add(AppealEntry(kind="NEGATIVA", procedure="Artroplastia total do joelho", outcome="INDEFERIDA", text=PAST + " Outra."))
    lib.add(AppealEntry(kind="GLOSA", procedure="Reconstrução do LCA", outcome="PENDENTE", text=PAST + " Glosa."))
    assert oct(os.stat(tmp_path / "appeals.json").st_mode & 0o777) == "0o600"
    examples = lib.examples("NEGATIVA", "artroplastia joelho")
    assert examples[0].appeal_id == granted.appeal_id and all(e.outcome != "INDEFERIDA" for e in examples)
    labelled = lib.add(AppealEntry(kind="GLOSA", text=PAST + " Paciente: Maria Helena Duarte"))
    assert "Maria" not in labelled.text
    lib.delete(labelled.appeal_id)
    with pytest.raises(AppealLibraryRejected):
        lib.set_outcome(granted.appeal_id, "GANHA")
    saved = lib.add(AppealEntry(kind="GLOSA", text=PAST + f" CPF {SYNTHETIC_TAX_ID} e-mail fulano@exemplo.com."))
    assert SYNTHETIC_TAX_ID not in saved.text and "fulano@" not in saved.text
    assert lib.set_outcome(saved.appeal_id, "DEFERIDA").outcome == "DEFERIDA"
    lib.delete(saved.appeal_id)
    assert len(lib.entries()) == 3


def test_contestation_keeps_only_grounded_sentences():
    svc, adapter = service(OUTPUT)
    with TenantContextBinder().bind_tenant(TENANT):
        draft = svc.draft(kind="NEGATIVA", denial_text=DENIAL.replace(SYNTHETIC_TAX_ID, "[CPF REMOVIDO]"), facts=FACTS,
                          context="Procedimento: ATJ", sbot="", examples=[PAST])
    text = {k: [s.text for s in ss] for k, _, ss in draft.sections}
    assert draft.dropped == 3 and text["clinico"] == ["A paciente fez fisioterapia por 6 meses."]
    assert text["normativo"] and text["pedido"] and "L-RN424" in draft.sources and draft.gaps == ("Sem laudo de RM anexado.",)
    payload = adapter.requests[0].canonical_payload
    assert "EXEMPLO1" in payload and "L-CFM1956-ART5" in payload
    with pytest.raises(AppealDraftRejected):
        svc.draft(kind="GLOSA", denial_text="  ", facts=[], context="", sbot="", examples=[])
    assert denial_sentences("Negado. Falta laudo de imagem do joelho; sem justificativa do OPME.") == [
        "Falta laudo de imagem do joelho;", "sem justificativa do OPME."]


def test_appeal_endpoints(tmp_path):
    lib = AppealLibrary(tmp_path / "appeals.json")
    app = create_app(pubmed=SearchablePubMed(), crossref=Crossref(), clock=lambda: NOW, token=TOKEN, appeal_library=lib,
                     resolve_appeal_writer=lambda: (lambda: service(OUTPUT)[0]))
    c = TestClient(app, base_url="http://127.0.0.1:8770")
    upload = {"name": "contestacao.txt", "content_base64": base64.b64encode(("Paciente: Maria Helena Duarte\n" + PAST).encode()).decode()}
    preview = c.post("/api/appeals/preview", headers=H, json=upload).json()
    assert "Maria" not in preview["text"] and c.get("/api/appeals", headers=H).json() == {"entries": []}
    body = {"kind": "NEGATIVA", "procedure": "ATJ", "outcome": "DEFERIDA", "text": preview["text"], "confirmed": False}
    assert c.post("/api/appeals", headers=H, json=body).status_code == 400
    appeal_id = c.post("/api/appeals", headers=H, json=dict(body, confirmed=True)).json()["appeal_id"]
    assert c.patch(f"/api/appeals/{appeal_id}", headers=H, json={"outcome": "PARCIAL"}).json()["outcome"] == "PARCIAL"
    assert c.patch("/api/appeals/nope", headers=H, json={"outcome": "PARCIAL"}).status_code == 404
    job = c.post("/api/appeal/draft", headers=H, json={"kind": "NEGATIVA", "denial_text": DENIAL, "procedure": "ATJ",
                                                       "identifiers": {"cpf": SYNTHETIC_TAX_ID}}).json()
    assert job["examples"] == 1
    for _ in range(50):
        job = c.get(f"/api/appeal/draft/{job['job_id']}", headers=H).json()
        if job["status"] != "RUNNING":
            break
        time.sleep(0.05)
    assert job["status"] == "READY" and job["sections"][0]["sentences"]
    assert c.post("/api/appeal/draft", json={"kind": "NEGATIVA", "identifiers": {}}).status_code in (401, 403)
    no_ai = TestClient(create_app(pubmed=SearchablePubMed(), crossref=Crossref(), token=TOKEN), base_url="http://127.0.0.1:8770")
    assert no_ai.post("/api/appeal/draft", headers=H, json={"kind": "NEGATIVA", "denial_text": DENIAL, "identifiers": {}}).status_code == 503
    assert no_ai.get("/api/appeals", headers=H).status_code == 503
