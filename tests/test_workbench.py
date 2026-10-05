import json

import pytest
from fastapi.testclient import TestClient

from jmoraIs.application.support_classification_runtime import build_service
from jmoraIs.workbench.app import create_app, default_classifier_factory
from tests.test_scientific_justification import NOW, Crossref, PubMed
from tests.test_support_classification import CLAIM, QUOTE

TOKEN = "t" * 43


class SearchablePubMed(PubMed):
    def mesh_headings_for(self, phrase):
        return ("osteoarthritis, knee",) if phrase == "knee osteoarthritis" else ()

    def search_by_title(self, title):
        self.last_query = title
        return [self.search_by_pmid("26488691")]


class FakeTransport:
    def __init__(self, text):
        self.text = text

    def send(self, provider, request):
        from tests.test_llm_gateway import response
        return response(output_text=self.text)


def client(classifier_factory=None, pubmed=None):
    app = create_app(pubmed=pubmed or SearchablePubMed(), crossref=Crossref(), classifier_factory=classifier_factory,
                     clock=lambda: NOW, token=TOKEN)
    return TestClient(app, base_url="http://127.0.0.1:8770")


H = {"X-Workbench-Token": TOKEN}


def test_index_injects_token_and_sets_security_headers():
    r = client().get("/")
    assert r.status_code == 200 and TOKEN in r.text and "__WORKBENCH_TOKEN__" not in r.text
    assert r.headers["cache-control"] == "no-store" and r.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]


def test_foreign_host_and_missing_token_are_rejected():
    c = client()
    assert c.get("/", headers={"Host": "evil.example"}).status_code == 403
    assert c.get("/api/status").status_code == 403
    assert c.get("/api/status", headers={"X-Workbench-Token": "wrong"}).status_code == 403
    assert c.get("/api/status", headers=H).json() == {"model_configured": False, "decisions": 0}


def test_search_builds_pico_query_and_lists_candidates():
    pubmed = SearchablePubMed()
    r = client(pubmed=pubmed).post("/api/search", headers=H, json={
        "population": "knee osteoarthritis", "intervention": "total knee arthroplasty", "designs": ["rct"]})
    body = r.json()
    assert r.status_code == 200 and body["candidates"][0]["pmid"] == "26488691"
    assert body["mesh"] == [{"element": "population", "synonym": "knee osteoarthritis", "heading": "osteoarthritis, knee"}]
    assert pubmed.last_query == body["query"] and body["query"].endswith("(randomized controlled trial[pt])")
    bad = client().post("/api/search", headers=H, json={"population": 'x" OR 1', "intervention": "y"})
    assert bad.status_code == 400


def test_manual_flow_rejects_invented_quote_then_builds_document():
    c = client()
    base = {"claim": CLAIM, "pmid": "26488691", "direction": "SUPPORTING", "reviewer": "CRM-SP 1"}
    invented = c.post("/api/manual", headers=H, json={**base, "quote": "Surgery is always better than anything else"})
    assert invented.status_code == 400 and "literalmente" in invented.json()["detail"]
    ok = c.post("/api/manual", headers=H, json={**base, "quote": QUOTE})
    assert ok.status_code == 200 and ok.json()["model"] == "physician-manual"
    doc = c.post("/api/document", headers=H, json={"claim": CLAIM, "procedure": "Artroplastia total do joelho", "rol": "NAO",
                                                   "ans_analysis": "SEM_ANALISE", "crm": "CRM-SP 1", "autogestao": False,
                                                   "clinical_summary": "<script>x</script>"}).json()
    assert doc["included"] == 1 and "<script>x" not in doc["html"] and "N Engl J Med" in doc["html"]
    assert [q["status"] for q in doc["requirements"]] == ["ATENDIDO", "ATENDIDO", "PENDENTE", "ATENDIDO", "PENDENTE"]
    assert "Fundamentação jurídica" in doc["markdown"]
    assert c.delete("/api/decisions/26488691", headers=H).status_code == 200
    assert c.get("/api/decisions", headers=H).json() == []


def test_ai_proposal_requires_physician_decision_and_cannot_be_forged():
    ai = json.dumps({"direction": "SUPPORTING", "quote": QUOTE, "rationale": "Primary outcome favoured surgery"})
    c = client(classifier_factory=lambda: build_service("claude-opus-5-5", FakeTransport(ai)))
    assert c.post("/api/decide", headers=H, json={"proposal_id": "prop-forged", "decision": "ACCEPT",
                                                  "reviewer": "CRM-SP 1"}).status_code == 404
    proposal = c.post("/api/propose", headers=H, json={"claim": CLAIM, "pmid": "26488691"}).json()
    assert proposal["status"] == "PENDING_PHYSICIAN_REVIEW" and proposal["quote"] == QUOTE
    assert c.get("/api/decisions", headers=H).json() == []
    override = c.post("/api/decide", headers=H, json={"proposal_id": proposal["proposal_id"], "decision": "OVERRIDE",
                                                      "final_direction": "NEUTRAL", "reviewer": "CRM-SP 1"})
    assert override.status_code == 400  # reason required
    decided = c.post("/api/decide", headers=H, json={"proposal_id": proposal["proposal_id"], "decision": "ACCEPT",
                                                     "reviewer": "CRM-SP 1"}).json()
    assert decided["final_direction"] == "SUPPORTING" and decided["model"] == "claude-opus-5-5"


def test_without_model_proposal_is_503_and_unknown_abstract_is_404():
    c = client()
    assert c.post("/api/propose", headers=H, json={"claim": CLAIM, "pmid": "26488691"}).status_code == 503
    assert c.post("/api/abstract", headers=H, json={"pmid": "11111111"}).status_code == 404
    assert c.post("/api/abstract", headers=H, json={"pmid": "1 OR 1"}).status_code == 422


def test_default_classifier_factory_depends_on_credentials():
    no_key = lambda: None
    assert default_classifier_factory({}, keychain=no_key) is None
    assert default_classifier_factory({"ANTHROPIC_API_KEY": "x"}, keychain=no_key) is not None
    assert default_classifier_factory({}, keychain=lambda: "sk-ant-x") is not None
