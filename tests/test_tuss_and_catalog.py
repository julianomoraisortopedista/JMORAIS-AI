import io
import zipfile
from datetime import date

import pytest
from fastapi.testclient import TestClient

from jmoraIs.application.surgical_catalog import (
    CatalogRejected, CatalogStore, OpmeItem, ProcedureTemplate, Supplier, SupplierMaterial, starter_templates,
    supplier_warnings, validate_against_tuss,
)
from jmoraIs.reference.tuss import TussIndex, build_index
from jmoraIs.workbench.app import create_app
from tests.test_scientific_justification import NOW, Crossref
from tests.test_workbench import H, TOKEN, SearchablePubMed


def xlsx(rows):
    def cell(ref, value):
        return f'<c r="{ref}" t="inlineStr"><is><t>{value}</t></is></c>'
    body = "".join(f'<row r="{i}">' + "".join(cell(f"{chr(65 + j)}{i}", v) for j, v in enumerate(r) if v != "") + "</row>"
                   for i, r in enumerate(rows, 1))
    sheet = ('<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
             + body + "</sheetData></worksheet>")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("xl/worksheets/sheet1.xml", sheet)
    return out.getvalue()


@pytest.fixture()
def index(tmp_path):
    package = tmp_path / "Padrao_TISS_Representacao_de_Conceitos_em_Saude_202609.zip"
    t22 = xlsx([["Tabela 22"], ["Código do Termo", "Termo", "Descrição", "Início", "Fim"],
                ["30726034", "Artroplastia total de joelho com implantes - tratamento cirúrgico", "", "39857", ""],
                ["30726280", "Toalete cirúrgica - correção de joelho flexo - tratamento cirúrgico", "", "39857", ""],
                ["39999999", "Procedimento encerrado", "", "39857", "40000"]])
    t19 = xlsx([["Tabela 19"], ["Código", "Termo", "Modelo", "Fabricante", "Início", "Fim", "Impl", "Registro Anvisa", "Classe", "Nome técnico"],
                ["70000001", "COMPONENTE FEMORAL MODELO A", "A1", "FABRICANTE UM LTDA", "42835", "", "", "10000000001", "III", "Componente femoral para artroplastia de joelho"],
                ["70000002", "COMPONENTE FEMORAL MODELO B", "B1", "FABRICANTE DOIS LTDA", "42835", "", "", "10000000002", "III", "Componente femoral para artroplastia de joelho"],
                ["70000003", "COMPONENTE FEMORAL MODELO C", "C1", "FABRICANTE TRES SA", "42835", "", "", "10000000003", "III", "Componente femoral para artroplastia de joelho"],
                ["70000009", "COMPONENTE ANTIGO", "Z", "FABRICANTE UM LTDA", "42835", "43000", "", "10000000009", "III", "x"]])
    with zipfile.ZipFile(package, "w") as z:
        z.writestr("pkg/TUSS 22 - PROCEDIMENTOS - VERSÃO 202609.xlsx", t22)
        z.writestr("pkg/TUSS 19 - materiais e OPME - VERSÃO 202609_PARTE_1.xlsx", t19)
        z.writestr("pkg/~$TUSS 19 lock.xlsx", b"ignored")
    output = tmp_path / "tuss.sqlite"
    assert build_index(package, output) == {"procedures": 3, "materials": 4}
    return TussIndex(output, today=lambda: date(2026, 10, 6))


def test_index_searches_official_terms_and_flags_expired(index):
    assert index.version() == "202609"
    assert [e.code for e in index.procedures("artroplastia joelho")] == ["30726034"]
    assert index.procedures("39999999")[0].active is False
    found = index.materials("componente femoral", "fabricante dois")
    assert [(e.code, e.anvisa, e.manufacturer) for e in found] == [("70000002", "10000000002", "FABRICANTE DOIS LTDA")]
    assert index.materials("70000009")[0].active is False
    assert index.procedures("") == [] and index.procedures('"; DROP TABLE') == []


def template(**kw):
    values = dict(name="ATJ", tuss_codes=["30726034"], codes_confirmed=True, opme=[OpmeItem(description="Componente femoral")],
                  suppliers=[Supplier(label=f"F{n}", materials=[SupplierMaterial(item_index=0, tuss_code=f"7000000{n}")]) for n in (1, 2, 3)])
    values.update(kw)
    return ProcedureTemplate(**values)


def test_validation_copies_official_data_and_rejects_unknown_or_expired(index):
    checked = validate_against_tuss(template(), index)
    assert checked.tuss_terms["30726034"].startswith("Artroplastia total")
    assert [m.anvisa for s in checked.suppliers for m in s.materials] == ["10000000001", "10000000002", "10000000003"]
    assert supplier_warnings(checked) == []
    for bad in (template(tuss_codes=["12345678"]), template(tuss_codes=["39999999"]),
                template(suppliers=[Supplier(label="XX", materials=[SupplierMaterial(item_index=0, tuss_code="70000009")])]),
                template(suppliers=[Supplier(label="XX", materials=[SupplierMaterial(item_index=3, tuss_code="70000001")])])):
        with pytest.raises(CatalogRejected):
            validate_against_tuss(bad, index)


def test_three_brands_from_different_manufacturers_rule(index):
    same = validate_against_tuss(template(suppliers=[Supplier(label=f"S{n}", materials=[SupplierMaterial(item_index=0, tuss_code="70000001")]) for n in range(3)]), index)
    assert any("fabricantes diferentes" in w for w in supplier_warnings(same))
    two = validate_against_tuss(template(suppliers=template().suppliers[:2]), index)
    assert any("três fornecedores" in w for w in supplier_warnings(two))
    assert any("não confirmados" in w for w in supplier_warnings(template(codes_confirmed=False)))


def test_store_seeds_once_and_saves_atomically(tmp_path):
    store = CatalogStore(tmp_path / "catalog" / "procedures.json")
    store.seed(starter_templates())
    names = [t.name for t in store.load()]
    assert "Artroplastia total do joelho com implantes" in names and len(names) == 6
    assert all(not t.codes_confirmed for t in store.load())
    saved = store.save(template(template_id=""))
    assert saved.template_id.startswith("tpl-")
    store.seed([])  # never overwrites an existing catalog
    assert len(store.load()) == 7
    store.delete(saved.template_id)
    assert len(store.load()) == 6
    assert oct((tmp_path / "catalog" / "procedures.json").stat().st_mode & 0o777) == "0o600"


def test_catalog_endpoints_and_template_in_request_document(index, tmp_path):
    store = CatalogStore(tmp_path / "procedures.json")
    c = TestClient(create_app(pubmed=SearchablePubMed(), crossref=Crossref(), clock=lambda: NOW, token=TOKEN,
                              tuss_index=index, catalog=store), base_url="http://127.0.0.1:8770")
    assert c.get("/api/tuss/procedures", params={"q": "joelho flexo"}, headers=H).json()["results"][0]["code"] == "30726280"
    assert c.get("/api/tuss/materials", params={"q": "femoral", "manufacturer": "tres"}, headers=H).json()["results"][0]["anvisa"] == "10000000003"
    bad = template(tuss_codes=["12345678"]).model_dump()
    assert c.put("/api/catalog", headers=H, json=bad).status_code == 400
    saved = c.put("/api/catalog", headers=H, json=template(template_id="", codes_confirmed=False).model_dump()).json()
    assert saved["warnings"] == ["Códigos TUSS ainda não confirmados pelo médico."]
    doc = {"claim": "Total knee replacement improves pain versus nonsurgical care", "procedure": "ATJ", "rol": "SIM",
           "template_id": saved["template_id"]}
    assert c.post("/api/document", headers=H, json=doc).status_code == 400  # codes not confirmed
    c.put("/api/catalog", headers=H, json={**saved, "codes_confirmed": True})
    html = c.post("/api/document", headers=H, json=doc).json()["html"]
    assert "30726034" in html and "Artroplastia total de joelho com implantes" in html
    assert "FABRICANTE TRES SA" in html and "10000000002" in html and "CFM, Resolução nº 1.956/2010, art. 5º" in html
    assert c.delete(f"/api/catalog/{saved['template_id']}", headers=H).status_code == 200
    assert TestClient(create_app(pubmed=SearchablePubMed(), crossref=Crossref(), token=TOKEN), base_url="http://127.0.0.1:8770").get(
        "/api/catalog", headers=H).status_code == 503


def test_seed_copies_official_terms_and_warning_waits_for_materials(index, tmp_path):
    store = CatalogStore(tmp_path / "p.json")
    store.seed([ProcedureTemplate(name="ATJ", tuss_codes=["30726034"], opme=[OpmeItem(description="Componente femoral")],
                                  suppliers=[Supplier(label=f"F{n}") for n in range(3)])], index)
    seeded = store.load()[0]
    assert seeded.tuss_terms["30726034"].startswith("Artroplastia total")
    assert not any("fabricantes diferentes" in w for w in supplier_warnings(seeded))


def test_supplier_contact_equivalent_brands_and_anvisa_reference_persist(tmp_path):
    from jmoraIs.application.surgical_catalog import CatalogStore, OpmeItem, ProcedureTemplate, Supplier
    store = CatalogStore(tmp_path / "p.json")
    saved = store.save(ProcedureTemplate(name="Bloqueio de nervos geniculares", opme=[OpmeItem(description="Kit cânula")],
                                         suppliers=[Supplier(label="Fornecedor A", contact="vendas@a.example")],
                                         equivalent_brands=["Marca 1", "Marca 2"], anvisa_reference="80000000001"))
    loaded = next(t for t in store.load() if t.template_id == saved.template_id)
    assert loaded.suppliers[0].contact == "vendas@a.example" and loaded.equivalent_brands == ["Marca 1", "Marca 2"]
    assert loaded.anvisa_reference == "80000000001"
