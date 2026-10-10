from fastapi.testclient import TestClient

from jmoraIs.application.legal_check import check_citations, verified_keys
from jmoraIs.workbench.app import create_app
from tests.test_scientific_justification import NOW, Crossref
from tests.test_workbench import H, TOKEN, SearchablePubMed


def test_verified_library_includes_the_ans_published_opme_norms():
    assert {"RN 424/2017", "RN 465/2021", "LEI 9656/1998", "CFM 1956/2010", "ADI 7265"} <= verified_keys()


def test_unknown_norms_are_flagged_and_known_ones_show_their_excerpt():
    text = ("Conforme a RN nº 424/2017 da ANS, cabe ao médico definir a OPME. A RN 999/2020 proíbe a operadora de "
            "impor material inferior. Lei 9.656/98. Resolução CFM nº 2.217/2018.")
    found = {c["norm"]: c for c in check_citations(text)}
    assert found["RN 424/2017"]["status"] == "VERIFIED" and "três marcas" in " ".join(s["excerpt"] for s in found["RN 424/2017"]["sources"])
    assert found["RN 999/2020"]["status"] == "NOT_VERIFIED" and "material inferior" in found["RN 999/2020"]["sentence"]
    assert found["LEI 9656/1998"]["status"] == "VERIFIED" and found["CFM 2217/2018"]["status"] == "NOT_VERIFIED"
    assert check_citations("Paciente com dor EVA 8, 3 meses de fisioterapia.") == []


def test_legal_check_endpoint():
    c = TestClient(create_app(pubmed=SearchablePubMed(), crossref=Crossref(), clock=lambda: NOW, token=TOKEN),
                   base_url="http://127.0.0.1:8770")
    r = c.post("/api/legal/check", headers=H, json={"text": "RDC 999/2021 exige"}).json()
    assert r["citations"][0]["norm"] == "RDC 999/2021" and r["citations"][0]["status"] == "NOT_VERIFIED"
