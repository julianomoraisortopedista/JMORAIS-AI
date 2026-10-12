import base64

from fastapi.testclient import TestClient

from jmoraIs.application.deidentification import detect_card_fields
from jmoraIs.workbench.app import create_app
from tests.test_scientific_justification import NOW, Crossref
from tests.test_workbench import H, TOKEN, SearchablePubMed

CARD = "BRADESCO SAUDE\nEMPRESARIAL TOP NACIONAL\nMARIA APARECIDA DOS SANTOS\n774 898 000531 017\nVALIDADE 12/2027\nANS 005711"


def test_card_photo_text_gives_number_and_name_but_not_insurer_words():
    found = detect_card_fields(CARD)
    assert found == {"card_number": "774 898 000531 017", "name": "Maria Aparecida dos Santos"}
    assert detect_card_fields("Ressonância do joelho. CID M17.1") == {}


def test_scan_prefills_card_fields_and_insurer_locally():
    c = TestClient(create_app(pubmed=SearchablePubMed(), crossref=Crossref(), clock=lambda: NOW, token=TOKEN),
                   base_url="http://127.0.0.1:8770")
    r = c.post("/api/case/scan", headers=H, json={"name": "carteirinha.txt", "content_base64": base64.b64encode(CARD.encode()).decode()}).json()
    assert r["identifiers"]["card_number"] == "774 898 000531 017" and r["identifiers"]["name"] == "Maria Aparecida dos Santos"
    assert r["insurer"] == "Bradesco"
