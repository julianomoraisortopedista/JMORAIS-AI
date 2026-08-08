from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

import requests

PUBMED_SEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_SUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"


def fetch_pubmed_ids(query: str, max_results: int = 5) -> list[str]:
    params = {
        "db": "pubmed",
        "term": query,
        "retmode": "json",
        "retmax": str(max_results),
    }
    response = requests.get(PUBMED_SEARCH_URL, params=params, timeout=20)
    response.raise_for_status()
    payload = response.json()
    return payload.get("esearchresult", {}).get("idlist", [])


def fetch_pubmed_summary(ids: list[str]) -> list[dict[str, Any]]:
    if not ids:
        return []
    params = {"db": "pubmed", "id": ",".join(ids), "retmode": "json"}
    response = requests.get(PUBMED_SUMMARY_URL, params=params, timeout=20)
    response.raise_for_status()
    payload = response.json()
    return list(payload.get("result", {}).values()) if isinstance(payload.get("result"), dict) else []


def search_pubmed(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    ids = fetch_pubmed_ids(query, max_results=max_results)
    results = fetch_pubmed_summary(ids)
    cleaned: list[dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict) or item.get("uid") is None:
            continue
        cleaned.append(
            {
                "pmid": str(item.get("uid", "")),
                "title": item.get("title") or "",
                "journal": item.get("fulljournalname") or item.get("source") or "",
                "year": item.get("pubdate", "")[:4] if isinstance(item.get("pubdate"), str) else None,
                "authors": [author.get("name", "") for author in item.get("authors", []) if isinstance(author, dict)],
                "doi": item.get("elocationid") if isinstance(item.get("elocationid"), str) and item.get("elocationid", "").startswith("10.") else None,
                "abstract": item.get("abstract") or "",
            }
        )
    return cleaned


def search_pubmed_json(query: str, max_results: int = 5) -> str:
    return json.dumps(search_pubmed(query, max_results=max_results))
