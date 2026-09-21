from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Callable
from uuid import uuid4

from jmoraIs.application.evidence_packages import ScientificEvidencePackagePort, publication_metadata_hash
from jmoraIs.scientific_domain import ArticleRecord, ScientificArticle, VerificationStatus, utc_now
from jmoraIs.verification import CitationVerificationGate


class VancouverBlockedError(RuntimeError):
    pass


class PublicationType(str, Enum):
    JOURNAL_ARTICLE = "journal_article"
    ELECTRONIC_ARTICLE = "electronic_article"
    GUIDELINE = "guideline"
    BOOK = "book"
    BOOK_CHAPTER = "book_chapter"


@dataclass(frozen=True)
class VancouverReference:
    citation_id: str
    package_id: str
    publication_type: str
    formatter_version: str
    rendered_text: str
    created_at: datetime


def format_author_list(authors: list[str], limit: int = 6) -> str:
    if not authors:
        raise VancouverBlockedError("author metadata is required")
    return ", ".join(authors) if len(authors) <= limit else ", ".join(authors[:limit]) + " et al"


class StrictVancouverFormatter:
    FORMATTER_VERSION = "vancouver-st05-1"

    def __init__(self, packages: ScientificEvidencePackagePort, *, clock=utc_now) -> None:
        self._packages = packages
        self._clock = clock
        self._formatters: dict[PublicationType, Callable[[ScientificArticle], str]] = {
            PublicationType.JOURNAL_ARTICLE: self._journal_article,
            PublicationType.ELECTRONIC_ARTICLE: self._electronic_article,
            PublicationType.GUIDELINE: self._guideline,
            PublicationType.BOOK: self._book,
            PublicationType.BOOK_CHAPTER: self._book_chapter,
        }

    def render(self, *, package_id: str, article: ScientificArticle) -> VancouverReference:
        if not isinstance(article, ScientificArticle):
            raise VancouverBlockedError("structured persisted metadata is required; model text is prohibited")
        package = self._packages.get(package_id)
        if package.verification_status != VerificationStatus.VERIFIED.value:
            raise VancouverBlockedError("only VERIFIED evidence packages may be formatted")
        if CitationVerificationGate.evaluate(article) != VerificationStatus.VERIFIED:
            raise VancouverBlockedError("article verification gate rejected the metadata")
        identities = {identity.article_id: identity for identity in package.publication_identities}
        identity = identities.get(article.article_id)
        if identity is None:
            raise VancouverBlockedError("article is not linked to the evidence package")
        if identity.metadata_hash != publication_metadata_hash(article):
            raise VancouverBlockedError("bibliographic metadata differs from the verified package")

        raw_type = (article.publication_type or PublicationType.JOURNAL_ARTICLE.value).lower()
        try:
            publication_type = PublicationType(raw_type)
        except ValueError as exc:
            raise VancouverBlockedError(f"unsupported publication type: {raw_type}") from exc
        rendered = self._formatters[publication_type](article)
        return VancouverReference(
            citation_id=uuid4().hex,
            package_id=package.package_id,
            publication_type=publication_type.value,
            formatter_version=self.FORMATTER_VERSION,
            rendered_text=rendered,
            created_at=self._clock(),
        )

    @staticmethod
    def _required(article: ScientificArticle, *fields: str) -> None:
        missing = [field for field in fields if not getattr(article, field, None)]
        if missing:
            raise VancouverBlockedError("missing required metadata: " + ", ".join(missing))

    def _journal_article(self, article: ScientificArticle) -> str:
        self._required(article, "authors", "title", "journal", "publication_year")
        text = f"{format_author_list(article.authors)}. {article.title}. {article.journal}. {article.publication_year}"
        if article.volume:
            text += f";{article.volume}"
            if article.issue:
                text += f"({article.issue})"
            if article.pages:
                text += f":{article.pages}"
        return self._finish(text, article.doi)

    def _electronic_article(self, article: ScientificArticle) -> str:
        self._required(article, "authors", "title", "journal", "publication_year", "url", "accessed_at")
        base = f"{format_author_list(article.authors)}. {article.title} [Internet]. {article.journal}. {article.publication_year}"
        return f"{base} [cited {article.accessed_at.isoformat()}]. Available from: {article.url}."

    def _guideline(self, article: ScientificArticle) -> str:
        self._required(article, "authors", "title", "publication_place", "publisher", "publication_year")
        return f"{format_author_list(article.authors)}. {article.title}. {article.publication_place}: {article.publisher}; {article.publication_year}."

    def _book(self, article: ScientificArticle) -> str:
        self._required(article, "authors", "title", "publication_place", "publisher", "publication_year")
        return f"{format_author_list(article.authors)}. {article.title}. {article.publication_place}: {article.publisher}; {article.publication_year}."

    def _book_chapter(self, article: ScientificArticle) -> str:
        self._required(article, "authors", "chapter_title", "editors", "book_title", "publication_place", "publisher", "publication_year", "pages")
        return (
            f"{format_author_list(article.authors)}. {article.chapter_title}. In: "
            f"{format_author_list(article.editors)}, editors. {article.book_title}. "
            f"{article.publication_place}: {article.publisher}; {article.publication_year}. p. {article.pages}."
        )

    @staticmethod
    def _finish(text: str, doi: str | None) -> str:
        return f"{text}. doi: {doi}." if doi else f"{text}."


def render_vancouver(article: ArticleRecord) -> str:
    """Legacy entry point: deliberately fail closed without an EvidencePackage."""
    status = CitationVerificationGate.evaluate(article)
    return (
        "Vancouver citation withheld: metadata status is "
        f"{status.value}; a validated EvidencePackage is required."
    )
