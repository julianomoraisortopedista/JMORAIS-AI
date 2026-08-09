from __future__ import annotations

from jmoraIs.scientific_domain import ArticleRecord
from jmoraIs.verification import CitationVerificationGate, VerificationStatus


def format_author_list(authors: list[str], limit: int = 6) -> str:
    if not authors:
        return "Unavailable"
    if len(authors) <= limit:
        return ", ".join(authors)
    return ", ".join(authors[:limit]) + " et al"


def render_vancouver(article: ArticleRecord) -> str:
    status = CitationVerificationGate.evaluate(article)

    if CitationVerificationGate.is_blocked(article):
        return f"Vancouver citation withheld: metadata status is {status.value}."

    if not article.title:
        return "Vancouver citation withheld: missing article title."
    if not article.authors:
        return "Vancouver citation withheld: missing author metadata."
    if not article.journal:
        return "Vancouver citation withheld: missing journal metadata."
    if article.publication_year is None:
        return "Vancouver citation withheld: missing publication year."

    author_text = format_author_list(article.authors)
    journal = article.journal
    year = article.publication_year
    citation = f"{author_text}. {article.title}. {journal}. {year}."

    if status == VerificationStatus.PARTIALLY_VERIFIED:
        warning = CitationVerificationGate.warning_for(article)
        return f"[PARTIALLY_VERIFIED] {citation} | {warning}"
    return citation
