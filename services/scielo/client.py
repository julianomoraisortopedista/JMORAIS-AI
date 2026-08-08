from __future__ import annotations

import json
from typing import Any

import requests

SCIELO_SEARCH_URL = "https://api.scielo.org/"


def search_scielo(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    params = {
        "q": query,
        "limit": str(max_results),
        "format": "json",
    }
    response = requests.get(SCIELO_SEARCH_URL, params=params, timeout=20)
    response.raise_for_status()
    payload = response.json()

    if isinstance(payload, dict):
        results = payload.get("results") or payload.get("items") or payload.get("hits") or []
    else:
        results = payload if isinstance(payload, list) else []

    if not isinstance(results, list):
        return []

    cleaned: list[dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        title = item.get("title") or item.get("title_display") or ""
        authors = item.get("authors") or []
        if isinstance(authors, str):
            author_list = [author.strip() for author in authors.split(";") if author.strip()]
        elif isinstance(authors, list):
            author_list = [str(author).strip() for author in authors if str(author).strip()]
        else:
            author_list = []
        year = item.get("year")
        if isinstance(year, str) and year.isdigit():
            year_value = int(year)
        elif isinstance(year, int):
            year_value = year
        else:
            year_value = None
        cleaned.append(
            {
                "title": title,
                "journal": item.get("journal") or item.get("source") or "",
                "year": year_value,
                "authors": author_list,
                "doi": item.get("doi") or item.get("identifier") or None,
                "abstract": item.get("abstract") or item.get("summary") or "",
                "source": "scielo",
                "source_locator": item.get("url") or item.get("link") or None,
            }
        )
    return cleaned


def search_scielo_json(query: str, max_results: int = 5) -> str:
    return json.dumps(search_scielo(query, max_results=max_results))
