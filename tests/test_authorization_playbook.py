import os

import pytest
from fastapi.testclient import TestClient

from jmoraIs.application.authorization_playbook import (
    Case, Insurer, Line, Playbook, PlaybookRejected, PlaybookStore, Reason, Rule, advice, match_insurer,
)
from jmoraIs.workbench.app import create_app
from tests.test_scientific_justification import NOW, Crossref
from tests.test_workbench import H, TOKEN, SearchablePubMed


def book():
    return Playbook(
        reasons=[Reason(reason_id="kit_substituido", label="Kit trocado", prevention=["Especificar o material"], evidence=["34171709"])],
        insurers=[Insurer(insurer_id="bradesco", name="Bradesco Saúde", aliases=["bradesco"],
                          rules=[Rule(codes=["31403026"], message="1x por articulação na Advice"),
                                 Rule(codes=[], message="Inclua fornecedor homologado")])],
        cases=[Case(case_id="cas-1", insurer_id="bradesco", on="2026-10-08", lines=[Line(code="31403026", requested=6, authorized=4)],
                    reasons=["kit_substituido"], outcome="APROVADO_PARCIAL")])


def test_advice_matches_insurer_by_alias_and_codes(tmp_path):
    b = book()
    assert match_insurer(b, "BRADESCO SAUDE - Empresarial Top").insurer_id == "bradesco"
    assert match_insurer(b, "Unimed") is None and match_insurer(b, "") is None
    a = advice(b, "Bradesco", ["31403026"])
    assert [w["message"] for w in a["warnings"]] == ["1x por articulação na Advice", "Inclua fornecedor homologado"]
    assert advice(b, "Bradesco", ["30713137"])["warnings"][0]["message"] == "Inclua fornecedor homologado"
    assert a["record"] == {"APROVADO_PARCIAL": 1} and a["top_reasons"][0]["count"] == 1


def test_store_refuses_patient_data_unknown_references_and_bad_pmids(tmp_path):
    store = PlaybookStore(tmp_path / "playbook.json")
    store.replace(book())
    assert oct(os.stat(tmp_path / "playbook.json").st_mode & 0o777) == "0o600"
    with pytest.raises(PlaybookRejected):
        store.add_case(Case(insurer_id="bradesco", on="2026-10-11", notes="Paciente: Maria da Silva Souza, CPF 123.456.789-09"))
    with pytest.raises(PlaybookRejected):
        store.add_case(Case(insurer_id="unimed", on="2026-10-11"))
    with pytest.raises(PlaybookRejected):
        store.add_case(Case(insurer_id="bradesco", on="2026-10-11", reasons=["inventado"]))
    with pytest.raises(ValueError):
        Reason(reason_id="x_y_z", label="abc", evidence=["not-a-pmid"])
    saved = store.add_case(Case(insurer_id="bradesco", on="2026-10-11", reasons=["kit_substituido"]))
    assert store.set_outcome(saved.case_id, "REVERTIDO").outcome == "REVERTIDO"
    with pytest.raises(PlaybookRejected):
        store.set_outcome(saved.case_id, "GANHO")


def test_playbook_endpoints(tmp_path):
    store = PlaybookStore(tmp_path / "playbook.json")
    store.replace(book())
    c = TestClient(create_app(pubmed=SearchablePubMed(), crossref=Crossref(), clock=lambda: NOW, token=TOKEN, playbook=store),
                   base_url="http://127.0.0.1:8770")
    assert c.get("/api/playbook", headers=H).json()["insurers"][0]["name"] == "Bradesco Saúde"
    assert c.get("/api/playbook/advice?insurer=bradesco&codes=31403026", headers=H).json()["insurer"] == "Bradesco Saúde"
    added = c.post("/api/playbook/cases", headers=H, json={"insurer_id": "bradesco", "on": "2026-10-11", "outcome": "NEGADO"})
    assert added.status_code == 200
    bad = c.post("/api/playbook/cases", headers=H, json={"insurer_id": "bradesco", "on": "2026-10-11", "notes": "Paciente: José Carlos da Silva"})
    assert bad.status_code == 400
    assert c.patch(f"/api/playbook/cases/{added.json()['case_id']}", headers=H, json={"outcome": "REVERTIDO"}).json()["outcome"] == "REVERTIDO"


def test_denial_text_reveals_insurer_reasons_and_codes():
    from jmoraIs.application.authorization_playbook import analyze, strategy_text
    b = book()
    b = b.model_copy(update={"reasons": [b.reasons[0].model_copy(update={"keywords": ["sem estímulo", "cânula convencional"],
                                                                          "response": ["Pedir a doutrina por escrito"]})],
                             "insurers": [b.insurers[0].model_copy(update={"responses": ["Orizon aprovou o kit"]})]})
    text = "Falo em nome da operadora Bradesco Saúde. 2x 31403026. Kit substituído por cânula convencional SEM ESTÍMULO."
    a = analyze(b, text)
    assert a["insurer"] == "Bradesco Saúde" and [r["reason_id"] for r in a["reasons"]] == ["kit_substituido"]
    assert a["codes"] == ["31403026"] and a["warnings"]
    s = strategy_text(a)
    assert "Pedir a doutrina por escrito" in s and "Orizon aprovou o kit" in s
    assert analyze(b, "Unimed nega por falta de laudo.")["insurer"] is None


def test_appeal_files_are_read_one_by_one_deidentified_and_analysed(tmp_path):
    import base64
    store = PlaybookStore(tmp_path / "playbook.json")
    store.replace(book())
    c = TestClient(create_app(pubmed=SearchablePubMed(), crossref=Crossref(), clock=lambda: NOW, token=TOKEN, playbook=store),
                   base_url="http://127.0.0.1:8770")
    mail = "Bradesco Saúde. Paciente: Maria Aparecida Souza. A paciente Maria Aparecida Souza teve o kit negado."
    r = c.post("/api/appeal/extract", headers=H, json={"file": {"name": "email.txt", "content_base64": base64.b64encode(mail.encode()).decode()},
                                                        "identifiers": {"name": "Maria Aparecida Souza"}})
    assert r.status_code == 200 and "Maria" not in r.json()["text"] and "Bradesco" in r.json()["text"]
    assert c.post("/api/appeal/analyze", headers=H, json={"text": r.json()["text"]}).json()["insurer"] == "Bradesco Saúde"


def test_strategy_reaches_the_writer_but_cannot_be_cited():
    from jmoraIs.tenancy.context import TenantContextBinder
    from tests.test_appeals import DENIAL, service
    from tests.test_report_drafting import TENANT
    out = {"sections": [{"section": "sintese", "sentences": [
        {"text": "A operadora negou por ausência de tratamento conservador.", "source_ids": ["N2"]},
        {"text": "Já revertemos isso antes.", "source_ids": ["ESTRATEGIA"]}]}], "gaps": []}
    svc, adapter = service(out)
    with TenantContextBinder().bind_tenant(TENANT):
        draft = svc.draft(kind="NEGATIVA", denial_text=DENIAL.replace("123.456.789-09", "[CPF REMOVIDO]"), facts=[], context="",
                          sbot="", examples=[], strategy="Motivo 'kit': pedir a doutrina por escrito")
    assert "ESTRATEGIA" in adapter.requests[0].canonical_payload
    assert [s.text for k, _, ss in draft.sections if k == "sintese" for s in ss] == ["A operadora negou por ausência de tratamento conservador."]


def test_physician_guidance_reaches_the_writer_deidentified_and_not_citable():
    from jmoraIs.tenancy.context import TenantContextBinder
    from tests.test_appeals import DENIAL, service
    from tests.test_report_drafting import TENANT
    out = {"sections": [{"section": "pedido", "sentences": [{"text": "Conforme orientado.", "source_ids": ["ORIENTACAO"]}]}], "gaps": []}
    svc, adapter = service(out)
    with TenantContextBinder().bind_tenant(TENANT):
        draft = svc.draft(kind="NEGATIVA", denial_text=DENIAL.replace("123.456.789-09", "[CPF REMOVIDO]"), facts=[], context="",
                          sbot="", examples=[], guidance="Aceite 1 bloqueio por joelho e mantenha o kit")
    assert "ORIENTACAO" in adapter.requests[0].canonical_payload and draft.dropped == 1
