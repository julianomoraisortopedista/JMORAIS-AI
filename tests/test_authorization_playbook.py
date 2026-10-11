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
