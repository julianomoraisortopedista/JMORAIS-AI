from __future__ import annotations

from typing import Any

from .base import BaseConnector


class PubMedConnector(BaseConnector):
    """PubMed connector contract placeholder for Sprint 2B.1."""

    def search_by_pmid(self, pmid: str) -> dict[str, Any]:
        raise NotImplementedError

    def search_by_doi(self, doi: str) -> dict[str, Any]:
        raise NotImplementedError

    def search_by_title(self, title: str) -> list[dict[str, Any]]:
        raise NotImplementedError
