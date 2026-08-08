from __future__ import annotations

from jmoraIs.verification import ArticleRecord


def format_author_list(authors: list[str], limit: int = 6) -> str:
    if not authors:
        return "Author"
    if len(authors) <= limit:
        return ", ".join(authors)
    return ", ".join(authors[:limit]) + " et al"


def render_vancouver(article: ArticleRecord) -> str:
    if not article.title:
        return "Unverified source. Vancouver citation cannot be generated."

    author_text = format_author_list(article.authors)
    journal = article.journal or "Journal"
    year = article.year or "n.d."
    if article.verification_status == "NOT_VERIFIED":
        return f"{author_text}. {article.title}. {journal}. {year}."
    return f"{author_text}. {article.title}. {journal}. {year}."
