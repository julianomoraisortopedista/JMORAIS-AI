from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseConnector(ABC):
    """Abstract contract for external scientific connectors."""

    @abstractmethod
    def search_by_pmid(self, pmid: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def search_by_doi(self, doi: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def search_by_title(self, title: str) -> list[dict[str, Any]]:
        raise NotImplementedError
