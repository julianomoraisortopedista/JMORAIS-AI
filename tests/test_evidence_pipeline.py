from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from jmoraIs.db import Base, EvidenceLedger, ScientificArticle, store_ledger_entry, upsert_article
from jmoraIs.verification import ArticleRecord, build_ledger_entry, normalize_article, verify_article_metadata
from jmoraIs.vancouver import render_vancouver
from services.pubmed import client


def test_normalize_and_verify_article_metadata() -> None:
    raw = {
        "title": "Evidence for early rehabilitation after knee surgery",
        "journal": "Orthopedic Review",
        "year": 2024,
        "pmid": "12345678",
        "doi": "10.1000/example",
        "authors": ["Doe, Jane", "Smith, John"],
        "source": "pubmed",
        "source_locator": "https://pubmed.ncbi.nlm.nih.gov/12345678/",
    }

    article = verify_article_metadata(normalize_article(raw))

    assert article.title == raw["title"]
    assert article.pmid == "12345678"
    assert article.verification_status == "VERIFIED"


def test_render_vancouver_citation() -> None:
    article = ArticleRecord(
        title="Comparative evidence for post-operative recovery",
        authors=["Doe, Jane", "Smith, John"],
        journal="British Medical Journal",
        year=2024,
        pmid="98765432",
        doi="10.1000/demo",
        verification_status="VERIFIED",
    )

    citation = render_vancouver(article)

    assert "Doe, Jane, Smith, John" in citation
    assert "British Medical Journal" in citation
    assert "2024" in citation


def test_search_pubmed_uses_mock_response(monkeypatch) -> None:
    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    def fake_get(url, params=None, timeout=20):
        if "esearch" in url:
            return FakeResponse({"esearchresult": {"idlist": ["12345678"]}})
        if "esummary" in url:
            return FakeResponse({
                "result": {
                    "12345678": {
                        "uid": "12345678",
                        "title": "Clinical outcomes after arthroplasty",
                        "fulljournalname": "Journal of Orthopedic Research",
                        "pubdate": "2024/01/01 00:00",
                        "authors": [{"name": "Doe, Jane"}, {"name": "Smith, John"}],
                        "elocationid": "10.1000/arthro",
                    }
                }
            })
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(client.requests, "get", fake_get)

    results = client.search_pubmed("arthroplasty", max_results=5)

    assert len(results) == 1
    assert results[0]["pmid"] == "12345678"
    assert results[0]["doi"] == "10.1000/arthro"


def test_store_article_and_ledger() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)

    with Session(engine) as session:
        article = verify_article_metadata(
            normalize_article(
                {
                    "title": "Evidence in postoperative rehabilitation",
                    "journal": "Clinical Journal of Sports Medicine",
                    "year": 2023,
                    "pmid": "55555",
                    "doi": "10.1000/postop",
                    "authors": ["Costa, Ana", "Leite, Marcos"],
                }
            )
        )
        stored_article = upsert_article(article, session)
        entry = build_ledger_entry(
            claim_id="claim-001",
            claim_text="Early mobilization improves recovery outcomes.",
            source_id=stored_article.id,
            source_type="scientific_article",
            source_locator="https://pubmed.ncbi.nlm.nih.gov/55555/",
            supporting_passage="Early mobilization is associated with improved recovery outcomes.",
            article=article,
            support_direction="supporting",
            confidence=0.93,
        )
        stored_entry = store_ledger_entry(entry, session)

        assert stored_article.id is not None
        assert stored_entry.claim_id == "claim-001"
        assert session.query(EvidenceLedger).count() == 1
        assert session.query(ScientificArticle).count() == 1
