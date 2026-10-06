import json

import pytest
from fastapi.testclient import TestClient

from jmoraIs.application.question_translation import QuestionTranslationRejected, QuestionTranslationService, question_prompt
from jmoraIs.application.surgical_catalog import CatalogStore, starter_templates
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

GOOD = {"claim": "Total knee arthroplasty improves pain versus nonsurgical care", "population": ["knee osteoarthritis", "gonarthrosis"],
        "intervention": ["total knee arthroplasty"], "comparison": ["nonsurgical treatment"], "outcome": ["pain"], "designs": ["rct", "sr", "bogus"]}


def service(output):
    prompts, audit = InMemoryPromptRepository(), InMemoryPromptAuditRepository()
    version = PromptGovernanceService(prompts, audit, clock=lambda: NOW).register(question_prompt(), created_by="t")
    adapter = MockProviderAdapter((response(output_text=json.dumps(output) if isinstance(output, dict) else output),))
    gateway = CanonicalLLMGateway(prompts, audit, InMemoryInvocationRepository(), InMemoryLLMInvocationContextRepository(),
                                  (adapter,), clock=lambda: NOW)
    return QuestionTranslationService(gateway, prompt_version_id=version.prompt_version_id, model=model(LLMProvider.MOCK), clock=lambda: NOW), adapter


TENANT = TenantContext("t", "o", "dr", "CLINICIAN", "CLINICAL_DOCUMENTATION", "ST-02", "corr-question-test-01")


def translate(output, question="A artroplastia melhora a dor? CPF 123.456.789-09", context=""):
    svc, adapter = service(output)
    with TenantContextBinder().bind_tenant(TENANT):
        return svc.translate(question, context), adapter


def test_draft_is_cleaned_validated_and_identifier_patterns_removed():
    draft, adapter = translate(GOOD)
    assert draft.population == ("knee osteoarthritis", "gonarthrosis") and draft.designs == ("rct", "sr")
    assert "123.456.789-09" not in adapter.requests[0].canonical_payload


def test_query_syntax_from_model_is_stripped_or_rejected():
    draft, _ = translate({**GOOD, "population": ['knee" OR "hip', "knee [tiab]"]})
    assert all('"' not in t and "[" not in t for t in draft.population)
    with pytest.raises(QuestionTranslationRejected):
        translate({**GOOD, "intervention": []})
    with pytest.raises(QuestionTranslationRejected):
        translate("not json")
    with pytest.raises(QuestionTranslationRejected):
        translate(GOOD, question="", context="")


def test_endpoint_uses_template_context_and_requires_model(tmp_path):
    store = CatalogStore(tmp_path / "c.json")
    store.seed(starter_templates())
    captured = {}

    class Spy:
        def translate(self, question, context):
            captured["context"] = context
            return translate(GOOD)[0]

    c = TestClient(create_app(pubmed=SearchablePubMed(), crossref=Crossref(), clock=lambda: NOW, token=TOKEN, catalog=store,
                              resolve_question_translator=lambda: Spy), base_url="http://127.0.0.1:8770")
    tka = next(t for t in store.load() if t.name.startswith("Artroplastia"))
    r = c.post("/api/question", headers=H, json={"question": "", "template_id": tka.template_id}).json()
    assert r["intervention"] == ["total knee arthroplasty"] and "30726034" in captured["context"] and "Componente femoral" in captured["context"]
    off = TestClient(create_app(pubmed=SearchablePubMed(), crossref=Crossref(), token=TOKEN), base_url="http://127.0.0.1:8770")
    assert off.post("/api/question", headers=H, json={"question": "dor no joelho"}).status_code == 503
