import base64
from datetime import date, datetime, timezone
from email.message import EmailMessage
import os

from fastapi.testclient import TestClient

from jmoraIs.practice_finance.importers import (
    guess_mapping, invoices_from_xml, parse_date, parse_money, payments_from_text, read_email, read_table,
    surgeries_from_table,
)
from jmoraIs.practice_finance.reconcile import apply_certain, panel, suggest
from jmoraIs.practice_finance.store import FinanceStore, Invoice, Payment, Surgery
from jmoraIs.workbench.app import create_app
from tests.test_scientific_justification import Crossref
from tests.test_workbench import H, TOKEN, SearchablePubMed

CSV = ("Controle cirúrgico 2026\n"
       "Data;Hospital;Convênio;Paciente;Procedimento;TUSS;Função;Valor;Guia\n"
       "05/09/2026;Hospital Santa Cruz;Unimed;Paciente Ficticio Um;ATJ direita;30726034;Cirurgião;R$ 3.500,00;G1\n"
       "12/09/2026;Hospital São Luiz;Bradesco;Paciente Ficticio Dois;Artroscopia joelho;30733014;Cirurgião;1.200,50;G2\n"
       ";;;;;;;;\n")
XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<CompNfse xmlns="http://www.abrasf.org.br/nfse.xsd"><Nfse><InfNfse>
<Numero>000123</Numero><DataEmissao>2026-09-20T10:00:00</DataEmissao>
<Servico><Valores><ValorServicos>3500.00</ValorServicos></Valores>
<Discriminacao>Honorarios medicos: Paciente Ficticio Um - ATJ 05/09/2026</Discriminacao></Servico>
<TomadorServico><IdentificacaoTomador><CpfCnpj><Cnpj>11222333000144</Cnpj></CpfCnpj></IdentificacaoTomador>
<RazaoSocial>Sociedade Hospital Santa Cruz Ltda</RazaoSocial></TomadorServico>
</InfNfse></Nfse></CompNfse>"""


def test_values_and_dates():
    assert parse_money("R$ 3.500,00") == 350000 and parse_money("1200.5") == 120050 and parse_money("1,234.56") == 123456
    assert parse_money("") == 0 and parse_money(12.3) == 1230
    assert parse_date("05/09/2026") == "2026-09-05" and parse_date("2026-09-20T10:00") == "2026-09-20"
    assert parse_date("46270") == "2026-09-05" and parse_date("31/02/2026") == "" and parse_date("x") == ""


def test_spreadsheet_import_maps_columns():
    rows = read_table("controle.csv", CSV.encode())
    surgeries, skipped, info = surgeries_from_table(rows)
    assert [s.patient for s in surgeries] == ["Paciente Ficticio Um", "Paciente Ficticio Dois"]
    assert surgeries[0].expected_cents == 350000 and surgeries[1].codes == "30733014" and surgeries[0].insurer == "Unimed"
    assert info["mapping"]["date"] == 0 and skipped == []
    assert guess_mapping(["Data da cirurgia", "Data do pagamento", "Valor previsto"])["date"] == 0


def test_invoice_xml_and_payment_email():
    inv = invoices_from_xml(XML)[0]
    assert (inv.number, inv.issue_date, inv.value_cents, inv.hospital_doc) == ("123", "2026-09-20", 350000, "11222333000144")
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["Date"] = "Repasse de honorários", "financeiro@santacruz.example", "Fri, 02 Oct 2026 10:00:00 -0300"
    msg.set_content("Prezado doutor,\nCrédito referente à NF 123: R$ 3.200,00 em 02/10/2026.\nAtenciosamente")
    mail = read_email(bytes(msg))
    assert mail["date"] == "2026-10-02" and "NF 123" in mail["text"]
    found = payments_from_text(mail["text"], "Hospital Santa Cruz", mail["date"], "email")
    assert len(found) == 1 and found[0].value_cents == 320000 and found[0].reference == "NF 123"


def test_reconciliation_links_and_alerts(tmp_path):
    store = FinanceStore(tmp_path / "finance.sqlite")
    assert oct(os.stat(tmp_path / "finance.sqlite").st_mode & 0o777) == "0o600"
    s1 = store.save_surgery(Surgery(date="2026-09-05", hospital="Hospital Santa Cruz", patient="Paciente Ficticio Um",
                                    procedure="ATJ", expected_cents=350000))
    s2 = store.save_surgery(Surgery(date="2026-07-01", hospital="Hospital São Luiz", patient="Paciente Ficticio Dois",
                                    procedure="Artroscopia", expected_cents=120050))
    inv, created = store.save_invoice(invoices_from_xml(XML)[0])
    assert created and store.save_invoice(invoices_from_xml(XML)[0])[1] is False  # same number + CNPJ: no duplicate
    store.save_payment(Payment(date="2026-10-02", payer="Hospital Santa Cruz", value_cents=320000, reference="NF 123"))
    assert store.save_payment(Payment(date="2026-10-02", payer="Hospital Santa Cruz", value_cents=320000, reference="NF 123"))[1] is False
    assert {s.kind for s in suggest(store) if s.certain} == {"SURGERY_INVOICE", "PAYMENT_INVOICE"}
    assert apply_certain(store) == 2
    result = panel(store, date(2026, 10, 8))
    assert result["statuses"][s1.id] == "PAGA_PARCIAL" and result["statuses"][s2.id] == "REALIZADA"
    kinds = {a["kind"] for a in result["alerts"]}
    assert {"PAGO_A_MENOR", "SEM_NOTA"} <= kinds
    assert result["totals"]["a_receber"] == 30000 and result["totals"]["a_faturar"] == 120050


def test_finance_endpoints(tmp_path):
    store = FinanceStore(tmp_path / "finance.sqlite")
    app = create_app(pubmed=SearchablePubMed(), crossref=Crossref(), token=TOKEN, finance=store,
                     clock=lambda: datetime(2026, 10, 8, tzinfo=timezone.utc))
    c = TestClient(app, base_url="http://127.0.0.1:8770")
    file = {"name": "controle.csv", "content_base64": base64.b64encode(CSV.encode()).decode()}
    preview = c.post("/api/finance/import/surgeries", headers=H, json=file).json()
    assert preview["count"] == 2 and store.surgeries() == []
    assert c.post("/api/finance/import/surgeries", headers=H, json=dict(file, commit=True)).json()["added"] == 2
    assert c.post("/api/finance/import/surgeries", headers=H, json=dict(file, commit=True)).json()["duplicates"] == 2
    nf = c.post("/api/finance/import/invoices", headers=H, json={"name": "nota.xml", "content_base64": base64.b64encode(XML).decode()}).json()
    assert nf["added"] == 1 and nf["linked"] == 1
    statement = "Data;Nota;Valor pago\n02/10/2026;123;3.500,00\n"
    pay = c.post("/api/finance/import/payments", headers=H, json={"name": "repasse.csv", "payer": "Hospital Santa Cruz",
                                                                    "content_base64": base64.b64encode(statement.encode()).decode()}).json()
    assert pay["added"] == 1 and pay["linked"] == 1
    result = c.get("/api/finance/panel", headers=H).json()
    assert sorted(result["statuses"].values()) == ["PAGA", "REALIZADA"]
    assert c.post("/api/finance/import/invoices", headers=H, json={"name": "x.doc", "content_base64": ""}).status_code == 400
    assert c.get("/api/finance/panel").status_code in (401, 403)
    absent = TestClient(create_app(pubmed=SearchablePubMed(), crossref=Crossref(), token=TOKEN), base_url="http://127.0.0.1:8770")
    assert absent.get("/api/finance/panel", headers=H).status_code == 404


def test_one_note_per_xml_block_and_brazilian_formats(tmp_path):
    assert len(invoices_from_xml(XML)) == 1
    from jmoraIs.practice_finance.reconcile import br, brl
    assert brl(123456789) == "R$ 1.234.567,89" and brl(-5) == "-R$ 0,05" and br("2026-10-08") == "08/10/2026"


def xlsx(sheets):
    """Minimal workbook with inline strings: {sheet name: [[cell, ...], ...]}."""
    import io
    import zipfile
    from xml.sax.saxutils import escape
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rel = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        entries, rels = [], []
        for n, (name, rows) in enumerate(sheets.items(), 1):
            cells = "".join(f'<row r="{i}">' + "".join(f'<c r="{chr(65 + j)}{i}" t="inlineStr"><is><t>{escape(v)}</t></is></c>'
                                                      for j, v in enumerate(row)) + "</row>" for i, row in enumerate(rows, 1))
            z.writestr(f"xl/worksheets/sheet{n}.xml", f"<worksheet {ns}><sheetData>{cells}</sheetData></worksheet>")
            entries.append(f'<sheet name="{escape(name)}" sheetId="{n}" r:id="rId{n}"/>')
            rels.append(f'<Relationship Id="rId{n}" Type="worksheet" Target="worksheets/sheet{n}.xml"/>')
        z.writestr("xl/workbook.xml", f"<workbook {ns} {rel}><sheets>{''.join(entries)}</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels",
                   f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{"".join(rels)}</Relationships>')
    return buf.getvalue()


def test_workbook_one_sheet_per_hospital():
    from jmoraIs.practice_finance.importers import surgeries_from_workbook
    book = xlsx({"Hospital Alfa": [["Paciente", "Convênio", "Data", "Procedimento", "Valor"],
                                   ["Paciente Ficticio Um", "Sul América", "05/09/2026", "ATJ", "3.500,00"]],
                 "Hospital Beta": [["Data", "Paciente", "Procedimento"], ["12/09/2026", "Paciente Ficticio Dois", "Artroscopia"]],
                 "legendas": [["Cor", "Significado"], ["azul", "faturado"]]})
    surgeries, skipped, info = surgeries_from_workbook(book)
    assert [(s.hospital, s.patient) for s in surgeries] == [("Hospital Alfa", "Paciente Ficticio Um"), ("Hospital Beta", "Paciente Ficticio Dois")]
    assert surgeries[0].expected_cents == 350000 and surgeries[0].insurer == "Sul América"
    assert [s["count"] for s in info["sheets"]] == [1, 1, 0]
