from __future__ import annotations

from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from jmoraIs.config import get_database_url
from jmoraIs.db import Base, ScientificArticle, upsert_article
from jmoraIs.embeddings import ChromaVectorStore
from jmoraIs.verification import ArticleRecord, normalize_article, verify_article_metadata
from services.crossref.client import search_crossref
from services.pubmed.client import search_pubmed
from services.scielo.client import search_scielo
from jmoraIs.vancouver import render_vancouver


class ScientificEvidenceEngine:
    def __init__(self, database_url: str | None = None, chroma_path: str | None = None):
        self.database_url = database_url or get_database_url()
        self.engine = create_engine(self.database_url, future=True)
        Base.metadata.create_all(bind=self.engine)
        self.vector_store = ChromaVectorStore(persist_directory=chroma_path)

    def _index_articles(self, records: list[dict[str, Any]], source: str) -> list[ScientificArticle]:
        stored: list[ScientificArticle] = []
        with Session(self.engine) as session:
            for record in records:
                article = verify_article_metadata(normalize_article({**record, "source": source}))
                stored_article = upsert_article(article, session)
                stored.append(stored_article)
                doc_text = article.title
                if article.abstract:
                    doc_text = f"{article.title}. {article.abstract}"
                self.vector_store.add_document(
                    doc_id=f"{source}:{stored_article.id}",
                    text=doc_text,
                    metadata={
                        "article_id": str(stored_article.id),
                        "source": source,
                        "pmid": stored_article.pmid or "",
                        "doi": stored_article.doi or "",
                        "title": stored_article.title,
                    },
                )
        return stored

    def index_pubmed(self, query: str, max_results: int = 5) -> list[ScientificArticle]:
        records = search_pubmed(query, max_results=max_results)
        return self._index_articles(records, source="pubmed")

    def index_scielo(self, query: str, max_results: int = 5) -> list[ScientificArticle]:
        records = search_scielo(query, max_results=max_results)
        return self._index_articles(records, source="scielo")

    def index_crossref(self, query: str, max_results: int = 5) -> list[ScientificArticle]:
        records = search_crossref(query, max_results=max_results)
        return self._index_articles(records, source="crossref")

    def semantic_search(self, query: str, limit: int = 5, source: str | None = None) -> dict[str, Any]:
        where = {"source": source} if source else None
        return self.vector_store.semantic_search(query=query, limit=limit, where=where)

    def generate_vancouver_reference(self, article: ScientificArticle | ArticleRecord) -> str:
        if isinstance(article, ScientificArticle):
            article_record = ArticleRecord(
                title=article.title,
                authors=[author.strip() for author in (article.authors or "").split(",") if author.strip()],
                journal=article.journal,
                year=article.year,
                pmid=article.pmid,
                doi=article.doi,
                abstract=article.abstract,
                source=article.source,
                source_locator=article.source_locator,
                verification_status=article.verification_status,
            )
        else:
            article_record = article
        return render_vancouver(article_record)
