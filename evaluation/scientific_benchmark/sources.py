from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests
import time


class AuthoritativeSourceError(RuntimeError):
    pass


@dataclass
class AuthoritativeClients:
    timeout: float = 15.0

    def _get(self, url: str, **params: str) -> dict[str, Any]:
        error = None
        for attempt in range(3):
            try:
                response = requests.get(url, params=params, timeout=self.timeout,
                                        headers={"User-Agent": "JMORAIS-AI-authoritative-benchmark/2.0"})
                response.raise_for_status()
                payload = response.json()
                break
            except (requests.RequestException, ValueError) as exc:
                error = exc
                if attempt < 2: time.sleep(1.0 * (attempt + 1))
        else:
            raise AuthoritativeSourceError(f"authoritative source failed: {url}") from error
        if not isinstance(payload, dict):
            raise AuthoritativeSourceError(f"invalid authoritative payload: {url}")
        return payload

    def pubmed(self, pmid: str) -> dict[str, Any]:
        payload = self._get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
                            db="pubmed", id=pmid, retmode="json")
        result = payload.get("result", {}).get(pmid)
        if not isinstance(result, dict):
            raise AuthoritativeSourceError(f"PMID not confirmed: {pmid}")
        return result

    def pmc(self, pmcid: str) -> dict[str, Any]:
        payload = self._get("https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/",
                            ids=pmcid, format="json")
        records = payload.get("records", [])
        if not records or records[0].get("pmcid", "").upper() != pmcid.upper():
            raise AuthoritativeSourceError(f"PMCID not confirmed: {pmcid}")
        return records[0]

    def crossref(self, doi: str) -> dict[str, Any]:
        payload = self._get(f"https://api.crossref.org/works/{doi}")
        message = payload.get("message")
        if not isinstance(message, dict):
            raise AuthoritativeSourceError(f"DOI not confirmed by Crossref: {doi}")
        return message

    def openalex(self, doi: str) -> dict[str, Any]:
        return self._get(f"https://api.openalex.org/works/doi:{doi}")

    def semantic_scholar(self, doi: str) -> dict[str, Any]:
        return self._get(f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}",
                         fields="title,year,authors,externalIds,venue")
