from __future__ import annotations

from jmoraIs.scientific_domain import ArticleRecord


def format_author_list(authors: list[str], limit: int = 6) -> str:
    if not authors:
        return "Author"
    if len(authors) <= limit:
        return ", ".join(authors)
    return ", ".join(authors[:limit]) + " et al"


def render_vancouver(article: ArticleRecord) -> str:
    if article.verification_status != "VERIFIED":
        return (
            "Vancouver citation withheld: metadata is not verified. "
            f"Current status: {article.verification_status}."
        )
    if not article.title:
        return "Vancouver citation withheld: missing article title."

    author_text = format_author_list(article.authors or ["Author"])
    journal = article.journal or "Journal"
    year = article.year or "n.d."
    return f"{author_text}. {article.title}. {journal}. {year}."
