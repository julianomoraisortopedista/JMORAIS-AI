import base64
from datetime import date
import io
import json
import os
import zipfile

import pytest
from fastapi.testclient import TestClient

from jmoraIs.application.ans_deadlines import add_business_days, deadline_for
from jmoraIs.application.case_intake import CaseIntakeRejected, extract_text
from jmoraIs.application.practice_documents import PracticeRejected, PracticeStore, Profile
from jmoraIs.application.request_check import check_request
from jmoraIs.application.surgical_catalog import CatalogStore, template_from_sbot
from jmoraIs.reference.sbot import SbotIndex, parse_manual
from jmoraIs.workbench.app import create_app
from tests.test_scientific_justification import NOW, Crossref
from tests.test_workbench import H, TOKEN, SearchablePubMed

# Synthetic pages in the manual's layout (not the manual's text).
PAGES = ["""Manual de Diretrizes de Codificação Ortopedia e Traumatologia - SBOT
Nome do Procedimento 9.1 — PROCEDIMENTO SINTÉTICO DE JOELHO
Descrição do procedimento
Texto de descrição sintético.
CIDs do Procedimento M17.0, M17.1
Indicação Dor e falha do tratamento conservador.
Caráter da Indicação Eletiva
Contraindicação Infecção
Exames da Indicação Exame Clínico, Radiografia, Ressonância Magnética
Códigos CBHPM  Porte
3.07.26.03-4 Artroplastia sintética 10B
3.07.33.01-4 Sinovectomia total¹ 9C
3.07.33.02-2 Sinovectomia parcial ou subtotal¹ 8C
3.07.13.13-7 Punção articular diagnóstica. Quando orientada por RX,
cobrar código correspondente 4C
OPMEs
Descrição Quantidade
COMPONENTE FEMORAL 1
CIMENTO
ORTOPÉDICO 2
Internação UTI 1 dia(s) Quarto 3 dia(s)
Comentários (¹) Procedimentos excludentes entre si
12""", """Nome do Procedimento 9.2 — FRATURA SINTÉTICA
Descrição do procedimento
Outro texto.
CIDs do Procedimento S82.1
Caráter da Indicação ( ) Eletiva ( X ) Urgência ( X ) Emergência
Exames da Indicação Radiografia
Códigos CBHPM Decrição do procedimento Porte
3.07.27.01-3 Fratura sintética 9A
"""]


class Index:
    """In-memory SbotIndex built from the synthetic pages."""

    def __init__(self, tmp_path):
        entries = parse_manual(PAGES)
        path = tmp_path / "sbot.json"
        path.write_text(json.dumps({"source": "t", "sha256": "0" * 64, "pages": 2,
                                    "entries": [e.as_dict() for e in entries]}), encoding="utf-8")
        self.real = SbotIndex(path)

    def __getattr__(self, name):
        return getattr(self.real, name)


class Tuss:
    class E:
        def __init__(self, code, term):
            self.code, self.term, self.active = code, term, True
            self.model = self.manufacturer = self.anvisa = self.risk_class = self.technical_name = ""

    known = {"30726034": "Artroplastia total de joelho com implantes", "30733014": "Sinovectomia total",
             "30733022": "Sinovectomia parcial"}

    def procedures(self, q, limit=25):
        return [self.E(q, self.known[q])] if q in self.known else []

    def materials(self, q, manufacturer="", limit=40):
        return []

    def version(self):
        return "test"


def test_manual_entries_are_parsed_verbatim():
    first, second = parse_manual(PAGES)
    assert (first.entry_id, first.name, first.page) == ("9.1", "PROCEDIMENTO SINTÉTICO DE JOELHO", 1)
    assert first.icd10 == ("M17.0", "M17.1") and first.characters == ("ELETIVA",)
    assert [c.cbhpm for c in first.codes] == ["3.07.26.03-4", "3.07.33.01-4", "3.07.33.02-2", "3.07.13.13-7"]
    assert first.codes[1].exclusive_group == "1" and first.codes[1].description == "Sinovectomia total"
    assert first.codes[3].porte == "4C" and "cobrar código correspondente" in first.codes[3].description
    assert [(o.description, o.quantity) for o in first.opme] == [("COMPONENTE FEMORAL", 1), ("CIMENTO ORTOPÉDICO", 2)]
    assert (first.icu_days, first.ward_days) == (1, 3)
    assert second.characters == ("URGENCIA", "EMERGENCIA") and second.opme == ()


def test_index_search_and_template_from_sbot(tmp_path):
    index = Index(tmp_path)
    assert index.search("joelho sintetico")[0].entry_id == "9.1"
    assert index.search("30726034")[0].entry_id == "9.1"
    template = template_from_sbot(index.get("9.1"), Tuss())
    assert template.tuss_codes == ["30726034"] and template.sbot_entry == "9.1" and not template.codes_confirmed
    assert "30733014" in template.notes and "excludentes" in template.notes and "Não encontrados ativos na TUSS 22: 3.07.13.13-7" in template.notes
    assert [i.description for i in template.opme] == ["COMPONENTE FEMORAL", "CIMENTO ORTOPÉDICO"]
    assert template.regime == "Internação" and template.icu_days == 1


def test_request_check_flags_what_leads_to_denials(tmp_path):
    entry = Index(tmp_path).get("9.1")
    findings = check_request(entry, tuss_codes=["30726034", "30733014", "30733022", "99999999"], icd10=["M23.2"],
                             opme=[("Componente femoral", 2), ("Navegador", 1)], urgency="URGENCIA",
                             documents_text="Laudo de radiografia do joelho.")
    text = [(f.level, f.topic, f.message) for f in findings]
    assert any(l == "BLOQUEIO" and "excludentes" in m for l, _, m in text)
    assert any(t == "Códigos" and "99999999" in m for _, t, m in text)
    assert any(l == "BLOQUEIO" and t == "Caráter" for l, t, _ in text)
    assert any(t == "CID-10" and "fora da lista" in m for _, t, m in text)
    assert any(l == "OK" and t == "Exames" and "também cita ressonancia" in m for l, t, m in text)
    no_exam = check_request(entry, tuss_codes=[], icd10=[], opme=[], urgency="ELETIVA", documents_text="Dor no joelho.")
    assert any(f.level == "ATENCAO" and f.topic == "Exames" for f in no_exam)
    assert any(t == "OPME" and "Navegador" in m for _, t, m in text) and any("prevê 1" in m for _, _, m in text)
    clean = check_request(entry, tuss_codes=["30726034"], icd10=["M17.1"], opme=[("Componente femoral", 1)],
                          urgency="ELETIVA", documents_text="RX do joelho. RM: condropatia.")
    assert {f.level for f in clean} == {"OK"}


def test_ans_deadlines():
    assert add_business_days(date(2026, 10, 9), 1) == date(2026, 10, 12)  # Friday -> Monday
    d = deadline_for("Internação", "ELETIVA", date(2026, 10, 6))
    assert d.business_days == 21 and d.item == "XIII" and d.due == date(2026, 11, 4) and "566/2022" in d.text()
    assert deadline_for("Internação", "URGENCIA", date(2026, 10, 6)).text().startswith("Prazo máximo de atendimento pela operadora: imediato")
    assert deadline_for("Hospital-dia", "ELETIVA", date(2026, 10, 6)).business_days == 10
    assert deadline_for("", "ELETIVA", date(2026, 10, 6)) is None


def docx(paragraphs):
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    xml = ('<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/'
           f'wordprocessingml/2006/main"><w:body>{body}</w:body></w:document>')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("word/document.xml", xml)
    return buffer.getvalue()


CONSENT = ["TERMO DE CONSENTIMENTO LIVRE E ESCLARECIDO",
           "Eu, (inserir nome completo do paciente), autorizo o(a) médico(a) (inserir nome completo do médico assistente) "
           "a realizar (inserir o nome do procedimento), que consiste em (inserir uma breve definição do procedimento).",
           "(inserir, em tópicos, as possíveis complicações)",
           "Declaro que recebi as informações em linguagem clara e que posso revogar este consentimento.",
           "Nome do paciente: ______________", "CPF: ______________"]


def test_docx_text_and_practice_store(tmp_path):
    assert extract_text("termo.docx", docx(CONSENT)).splitlines()[0] == CONSENT[0]
    with pytest.raises(CaseIntakeRejected):
        extract_text("termo.docx", b"not a zip")
    store = PracticeStore(tmp_path / "practice.json")
    store.save_profile(Profile(name="Dr. Teste", crm="12345", uf="SP"))
    assert store.profile().crm == "12345" and oct(os.stat(tmp_path / "practice.json").st_mode & 0o777) == "0o600"
    assert store.save_consent_model("\n".join(CONSENT)).startswith("TERMO")
    with pytest.raises(PracticeRejected):  # a filled form of a real patient is refused
        store.save_consent_model("\n".join(CONSENT + ["Paciente: Maria Helena Duarte"]))
    store.delete_consent_model()
    assert store.consent_model() is None and store.profile().name == "Dr. Teste"


def test_endpoints(tmp_path):
    catalog = CatalogStore(tmp_path / "procedures.json")
    app = create_app(pubmed=SearchablePubMed(), crossref=Crossref(), clock=lambda: NOW, token=TOKEN, catalog=catalog,
                     tuss_index=Tuss(), sbot_index=Index(tmp_path), practice=PracticeStore(tmp_path / "practice.json"))
    c = TestClient(app, base_url="http://127.0.0.1:8770")
    assert c.get("/api/sbot/search?q=joelho", headers=H).json()["results"][0]["entry_id"] == "9.1"
    assert c.get("/api/sbot/entry/9.1", headers=H).json()["characters"] == ["ELETIVA"]
    assert c.get("/api/sbot/entry/1.1", headers=H).status_code == 404
    created = c.post("/api/catalog/from-sbot", headers=H, json={"entry_id": "9.1"}).json()
    assert created["sbot_entry"] == "9.1" and created["tuss_terms"]["30726034"].startswith("Artroplastia")
    assert c.post("/api/catalog/from-sbot", headers=H, json={"entry_id": "x"}).status_code == 422
    assert c.put("/api/profile", headers=H, json={"name": "Dr. Teste", "crm": "12345", "uf": "SP"}).status_code == 200
    upload = {"name": "termo.docx", "content_base64": base64.b64encode(docx(CONSENT)).decode()}
    assert c.post("/api/consent-model", headers=H, json=upload).json()["text"].startswith("TERMO")
    template = dict(created, codes_confirmed=True)
    template.pop("warnings")
    c.put("/api/catalog", headers=H, json=template)
    body = {"claim": "Total knee replacement improves pain versus nonsurgical care", "procedure": "Artroplastia",
            "template_id": created["template_id"], "urgency": "URGENCIA", "regime": "Internação"}
    result = c.post("/api/document", headers=H, json=body).json()
    assert any(f["level"] == "BLOQUEIO" and f["topic"] == "Caráter" for f in result["checks"])
    assert "imediato" in result["deadline"] and "SBOT, Manual de Diretrizes de Codificação, procedimento 9.1" in result["html"]
    no_sbot = TestClient(create_app(pubmed=SearchablePubMed(), crossref=Crossref(), token=TOKEN), base_url="http://127.0.0.1:8770")
    assert no_sbot.get("/api/sbot/search?q=joelho", headers=H).status_code == 503


def test_case_check_endpoint(tmp_path):
    catalog = CatalogStore(tmp_path / "procedures.json")
    app = create_app(pubmed=SearchablePubMed(), crossref=Crossref(), clock=lambda: NOW, token=TOKEN, catalog=catalog,
                     tuss_index=Tuss(), sbot_index=Index(tmp_path))
    c = TestClient(app, base_url="http://127.0.0.1:8770")
    created = c.post("/api/catalog/from-sbot", headers=H, json={"entry_id": "9.1"}).json()
    case = c.post("/api/case", headers=H, json={"history": "RX do joelho com artrose. RM: condropatia.",
                                                "identifiers": {"name": "Fulano Tal"}, "consent": True}).json()
    out = c.post(f"/api/case/{case['case_id']}/check", headers=H, json={"template_id": created["template_id"]}).json()
    assert out["sbot_entry"] == "9.1" and out["codes_confirmed"] is False and "21 dias úteis" in out["deadline"]
    assert any(f["topic"] == "Exames" and f["level"] == "OK" for f in out["checks"])
    assert c.post(f"/api/case/{case['case_id']}/check", headers=H, json={"template_id": "nope"}).status_code == 404


def test_letterhead_logo_is_validated(tmp_path):
    from jmoraIs.application.practice_documents import Letterhead
    png = b"\x89PNG\r\n\x1a\n" + b"\0" * 64
    store = PracticeStore(tmp_path / "practice.json")
    saved = store.save_letterhead(Letterhead(logo_base64=base64.b64encode(png).decode(), header_lines=[" Dr. Teste ", "", "Ortopedia"],
                                             footer="Rua  A, 1"))
    assert saved.logo_type == "image/png" and saved.header_lines == ["Dr. Teste", "Ortopedia"] and saved.footer == "Rua A, 1"
    assert store.letterhead().logo_type == "image/png"
    with pytest.raises(PracticeRejected):
        store.save_letterhead(Letterhead(logo_base64=base64.b64encode(b"<svg onload=x>").decode()))
    with pytest.raises(PracticeRejected):
        store.save_letterhead(Letterhead(logo_base64=base64.b64encode(png + b"\0" * 400_000).decode()))
    c = TestClient(create_app(pubmed=SearchablePubMed(), crossref=Crossref(), token=TOKEN, practice=store),
                   base_url="http://127.0.0.1:8770")
    assert c.get("/api/letterhead", headers=H).json()["header_lines"] == ["Dr. Teste", "Ortopedia"]
    assert c.put("/api/letterhead", headers=H, json={"logo_base64": base64.b64encode(b"GIF89a").decode()}).status_code == 400
    assert c.put("/api/letterhead", headers=H, json={"color": "red"}).status_code == 422
