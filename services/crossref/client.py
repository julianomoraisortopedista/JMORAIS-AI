from __future__ import annotations

import json
from typing import Any

import requests

CROSSREF_SEARCH_URL = "https://api.crossref.org/works"


def search_crossref(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    params = {
        "query.title": query,
        "rows": str(max_results),
        "select": "title,author,issued,DOI,container-title,abstract,URL",
    }
    response = requests.get(CROSSREF_SEARCH_URL, params=params, timeout=20)
    response.raise_for_status()
    payload = response.json()
    items = payload.get("message", {}).get("items", [])

    cleaned: list[dict[str, Any]] = []
    for item in items:
        title = item.get("title", [""])[0] if item.get("title") else ""
        author_names = []
        for author in item.get("author", []):
            family = author.get("family") or ""
            given = author.get("given") or ""
            full_name = f"{given} {family}".strip()
            if full_name:
                author_names.append(full_name)
        issued = item.get("issued", {}).get("date-parts", [[None]])[0]
        year = issued[0] if isinstance(issued, list) and issued and isinstance(issued[0], int) else None
        abstract = item.get("abstract") or ""
        cleaned.append(
            {
                "title": title,
                "journal": (item.get("container-title") or [""])[0] if item.get("container-title") else "",
                "year": year,
                "authors": author_names,
                "doi": item.get("DOI"),
                "abstract": abstract,
                "source": "crossref",
                "source_locator": item.get("URL"),
            }
        )
    return cleaned


def search_crossref_json(query: str, max_results: int = 5) -> str:
    return json.dumps(search_crossref(query, max_results=max_results))
