import os

import pytest
from fastapi.testclient import TestClient

from jmoraIs.application.evidence_library import EvidenceLibrary, EvidenceLibraryRejected
from jmoraIs.application.surgical_catalog import CatalogStore, starter_templates
from jmoraIs.workbench.app import create_app
from tests.test_scientific_justification import NOW, Crossref
from tests.test_support_classification import CLAIM, QUOTE
from tests.test_workbench import H, TOKEN, SearchablePubMed

TKA = "tpl-artroplastia-total-do-joelho-c"


def make(tmp_path):
    catalog = CatalogStore(tmp_path / "procedures.json")
    catalog.seed(starter_templates())
    library = EvidenceLibrary(tmp_path / "evidence_library.json")
    app = create_app(pubmed=SearchablePubMed(), crossref=Crossref(), clock=lambda: NOW, token=TOKEN,
                     catalog=catalog, evidence_library=library)
    return TestClient(app, base_url="http://127.0.0.1:8770"), library


def accept(c):
    ok = c.post("/api/manual", headers=H, json={"claim": CLAIM, "pmid": "26488691", "direction": "SUPPORTING",
                                                "reviewer": "CRM-SP 1", "quote": QUOTE})
    assert ok.status_code == 200


def test_library_keeps_only_this_sessions_physician_decisions_and_persists(tmp_path):
    c, library = make(tmp_path)
    empty = c.put(f"/api/library/{TKA}", headers=H, json={"claim": CLAIM})
    assert empty.status_code == 400  # nothing accepted by the physician yet
    accept(c)
    saved = c.put(f"/api/library/{TKA}", headers=H, json={"claim": CLAIM}).json()
    assert saved["claim"] == CLAIM and [a["pmid"] for a in saved["articles"]] == ["26488691"]
    assert oct(os.stat(tmp_path / "evidence_library.json").st_mode & 0o777) == "0o600"
    assert c.put("/api/library/tpl-unknown", headers=H, json={"claim": CLAIM}).status_code == 404
    # a new process (restart) still has the library; references are re-verified on use
    c2, _ = make(tmp_path)
    refs = c2.post(f"/api/library/{TKA}/justification", headers=H).json()
    assert [r["pmid"] for r in refs["references"]] == ["26488691"] and "N Engl J Med" in refs["references"][0]["vancouver"]
    assert refs["references"][0]["quote"] == QUOTE
    assert c2.delete(f"/api/library/{TKA}/26488691", headers=H).json()["articles"] == []
    assert c2.post(f"/api/library/{TKA}/justification", headers=H).json()["references"] == []


def test_library_never_accepts_rejected_foreign_claim_or_identifiers(tmp_path):
    library = EvidenceLibrary(tmp_path / "l.json")
    record = {"pmid": "1", "claim": CLAIM, "abstract_sha256": "h", "quote": QUOTE, "physician_decision": "ACCEPT",
              "final_direction": "SUPPORTING", "reviewer": "CRM 1", "decided_at": "2026-10-01"}
    with pytest.raises(EvidenceLibraryRejected):
        library.save("t", CLAIM, [{**record, "physician_decision": "REJECT"}])
    with pytest.raises(EvidenceLibraryRejected):
        library.save("t", CLAIM, [{**record, "claim": "another clinical claim entirely"}])
    with pytest.raises(EvidenceLibraryRejected):
        library.save("t", CLAIM + " CPF 123.456.789-09", [record])
    assert library.save("t", CLAIM, [record, {**record}])["records"] == [{**{k: None for k in (
        "source", "ai_status", "ai_direction", "ai_rationale", "model", "prompt_version", "note")}, **record}]


def test_tampered_library_record_is_excluded_on_use(tmp_path):
    c, library = make(tmp_path)
    accept(c)
    c.put(f"/api/library/{TKA}", headers=H, json={"claim": CLAIM})
    entry = library.get(TKA)
    entry["records"][0]["quote"] = "Surgery is always better than anything else in every patient"
    library.save(TKA, CLAIM, entry["records"])
    refs = c.post(f"/api/library/{TKA}/justification", headers=H).json()
    assert refs["references"] == [] and "literal" in refs["excluded"][0]["reason"]


def test_request_document_uses_the_surgery_library_and_lists_all_three_suppliers(tmp_path):
    c, _ = make(tmp_path)
    accept(c)
    c.put(f"/api/library/{TKA}", headers=H, json={"claim": CLAIM})
    store = CatalogStore(tmp_path / "procedures.json")
    store.save(next(t for t in store.load() if t.template_id == TKA).model_copy(update={"codes_confirmed": True}))
    c2, _ = make(tmp_path)  # fresh session: no in-memory decisions, only the library
    doc = c2.post("/api/document", headers=H, json={"claim": CLAIM, "procedure": "Artroplastia total do joelho",
                                                    "template_id": TKA}).json()
    assert doc["included"] == 1
    for supplier in ("Johnson &amp; Johnson", "Zimmer Biomet", "Amplitude"):
        assert supplier in doc["html"]


def test_report_cites_the_surgery_library_with_the_printed_numbering(tmp_path):
    import json
    import time
    from tests.test_case_intake import service as extraction_service
    from tests.test_report_drafting import service as report_service
    c, _ = make(tmp_path)
    accept(c)
    c.put(f"/api/library/{TKA}", headers=H, json={"claim": CLAIM})
    extraction = json.dumps({"facts": [{"category": "ESCALA_FUNCIONAL", "statement": "EVA 8/10", "quote": "EVA 8/10",
                                        "source": "História"}], "icd10_suggestions": []})
    report = {"sections": [{"section": "evidencias", "sentences": [
        {"text": "Ensaio randomizado apoia a indicação.", "fact_ids": ["E1", "F1"]},
        {"text": "Sem artigo citado.", "fact_ids": ["F1"]}]}], "gaps": []}
    writers = []

    def writer():
        svc, adapter = report_service(report)
        writers.append(adapter)
        return svc
    app = create_app(pubmed=SearchablePubMed(), crossref=Crossref(), clock=lambda: NOW, token=TOKEN,
                     catalog=CatalogStore(tmp_path / "procedures.json"), evidence_library=EvidenceLibrary(tmp_path / "evidence_library.json"),
                     resolve_case_extractor=lambda: (lambda: extraction_service(extraction)[0]),
                     resolve_report_writer=lambda: writer)
    c2 = TestClient(app, base_url="http://127.0.0.1:8770")
    cid = c2.post("/api/case", headers=H, json={"history": "Fulano com dor, EVA 8/10.", "identifiers": {"name": "Fulano Tal"},
                                                "consent": True}).json()["case_id"]
    c2.post(f"/api/case/{cid}/extract", headers=H)

    def wait(key):
        for _ in range(100):
            view = c2.get(f"/api/case/{cid}", headers=H).json()
            state = view["status"] if key is None else (view.get(key) or {}).get("status")
            if state != "RUNNING":
                return view
            time.sleep(0.05)
    view = wait(None)
    c2.post(f"/api/case/{cid}/confirm", headers=H, json={"fact_ids": [view["facts"][0]["fact_id"]]})
    c2.post(f"/api/case/{cid}/report", headers=H, json={"procedure": "ATJ", "template_id": TKA})
    view = wait("report")
    section = next(s for s in view["report"]["sections"] if s["key"] == "evidencias")
    assert [s["text"] for s in section["sentences"]] == ["Ensaio randomizado apoia a indicação. [1]"]
    assert [r["pmid"] for r in view["report"]["science"]["references"]] == ["26488691"]
    fields = json.loads(writers[0].requests[0].canonical_payload)["fields"]
    assert fields[-1]["name"] == "E1" and QUOTE in fields[-1]["value"]
