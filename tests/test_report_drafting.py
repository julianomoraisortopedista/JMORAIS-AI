import json
import time

import pytest

from jmoraIs.application.report_drafting import ReportDraftRejected, ReportDraftingService, report_prompt
from jmoraIs.llm_gateway import CanonicalLLMGateway, LLMProvider, MockProviderAdapter, PromptGovernanceService
from jmoraIs.llm_gateway.infrastructure import (
    InMemoryInvocationRepository, InMemoryLLMInvocationContextRepository, InMemoryPromptAuditRepository,
    InMemoryPromptRepository,
)
from jmoraIs.tenancy.context import TenantContextBinder
from jmoraIs.tenancy.domain import TenantContext
from tests.test_llm_gateway import model, response
from tests.test_scientific_justification import NOW

FACTS = [dict(category_label="Escala", statement="EVA 8/10.", quote="EVA 8/10"),
         dict(category_label="Tratamento", statement="Fisioterapia por 6 meses.", quote="fisioterapia por 6 meses")]
TENANT = TenantContext("t", "o", "dr", "CLINICIAN", "CLINICAL_DOCUMENTATION", "ST-02", "corr-report-unit-01")


def service(output):
    prompts, audit = InMemoryPromptRepository(), InMemoryPromptAuditRepository()
    version = PromptGovernanceService(prompts, audit, clock=lambda: NOW).register(report_prompt(), created_by="t")
    adapter = MockProviderAdapter((response(output_text=json.dumps(output) if isinstance(output, dict) else output),))
    gateway = CanonicalLLMGateway(prompts, audit, InMemoryInvocationRepository(), InMemoryLLMInvocationContextRepository(),
                                  (adapter,), clock=lambda: NOW)
    return ReportDraftingService(gateway, prompt_version_id=version.prompt_version_id, model=model(LLMProvider.MOCK), clock=lambda: NOW), adapter


def draft(output, facts=FACTS, context="Procedimento: ATJ. OPME: 1x Componente femoral"):
    svc, adapter = service(output)
    with TenantContextBinder().bind_tenant(TENANT):
        return svc.draft(facts, context), adapter


def test_only_grounded_sentences_survive_and_gaps_are_kept():
    output = {"sections": [
        {"section": "historia", "sentences": [
            {"text": "Paciente refere dor EVA 8/10.", "fact_ids": ["F1"]},
            {"text": "Paciente refere dor EVA 9/10.", "fact_ids": ["F1"]},              # invented number
            {"text": "Paciente tem 72 anos.", "fact_ids": ["F1"]},                     # invented age
            {"text": "Realizou fisioterapia por 6 meses.", "fact_ids": ["F9"]},       # nonexistent id
            {"text": "Sem citação.", "fact_ids": []}]},
        {"section": "opme", "sentences": [{"text": "Solicita-se 1 componente femoral.", "fact_ids": ["CTX"]}]},
        {"section": "inexistente", "sentences": [{"text": "x", "fact_ids": ["F1"]}]}],
        "gaps": ["Exame físico não documentado."]}
    result, adapter = draft(output)
    sections = {k: [s.text for s in ss] for k, _, ss in result.sections}
    assert sections["historia"] == ["Paciente refere dor EVA 8/10."] and sections["opme"] == ["Solicita-se 1 componente femoral."]
    assert sections["exame_fisico"] == [] and result.dropped == 4 and result.gaps == ("Exame físico não documentado.",)
    assert "História clínica: Paciente refere dor EVA 8/10." in result.as_text()
    payload = json.loads(adapter.requests[0].canonical_payload)
    assert [f["name"] for f in payload["fields"]] == ["F1", "F2", "CTX"]


def test_requires_facts_and_valid_output():
    with pytest.raises(ReportDraftRejected):
        draft({"sections": [], "gaps": []}, facts=[])
    with pytest.raises(ReportDraftRejected):
        draft("não é json")


def test_report_endpoint_requires_confirmation_then_runs(tmp_path):
    from fastapi.testclient import TestClient
    from jmoraIs.workbench.app import create_app
    from tests.test_case_intake import service as extraction_service
    from tests.test_scientific_justification import Crossref
    from tests.test_workbench import H, TOKEN, SearchablePubMed
    extraction = json.dumps({"facts": [{"category": "ESCALA_FUNCIONAL", "statement": "EVA 8/10", "quote": "EVA 8/10", "source": "História"}],
                             "icd10_suggestions": []})
    report = {"sections": [{"section": "historia", "sentences": [{"text": "Dor EVA 8/10.", "fact_ids": ["F1"]}]}], "gaps": ["Exame físico ausente."]}
    app = create_app(pubmed=SearchablePubMed(), crossref=Crossref(), clock=lambda: NOW, token=TOKEN,
                     resolve_case_extractor=lambda: (lambda: extraction_service(extraction)[0]),
                     resolve_report_writer=lambda: (lambda: service(report)[0]))
    c = TestClient(app, base_url="http://127.0.0.1:8770")
    case = c.post("/api/case", headers=H, json={"history": "Fulano com dor, EVA 8/10.", "identifiers": {"name": "Fulano Tal"}, "consent": True}).json()
    cid = case["case_id"]
    assert c.post(f"/api/case/{cid}/report", headers=H, json={}).status_code == 400  # not confirmed yet
    c.post(f"/api/case/{cid}/extract", headers=H)
    for _ in range(50):
        view = c.get(f"/api/case/{cid}", headers=H).json()
        if view["status"] != "RUNNING":
            break
        time.sleep(0.05)
    c.post(f"/api/case/{cid}/confirm", headers=H, json={"fact_ids": [view["facts"][0]["fact_id"]]})
    c.post(f"/api/case/{cid}/report", headers=H, json={"procedure": "ATJ", "laterality": "Direito"})
    for _ in range(50):
        view = c.get(f"/api/case/{cid}", headers=H).json()
        if view["report"]["status"] != "RUNNING":
            break
        time.sleep(0.05)
    assert view["report"]["status"] == "READY" and view["report"]["sections"][0]["sentences"][0]["text"] == "Dor EVA 8/10."
    assert view["report"]["gaps"] == ["Exame físico ausente."]
