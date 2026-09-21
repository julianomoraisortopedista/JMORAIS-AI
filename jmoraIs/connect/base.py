from __future__ import annotations

from abc import ABC, abstractmethod

from jmoraIs.scientific_domain import IdentifierVerificationResult


class BaseConnector(ABC):
    """Abstract contract for external scientific connectors."""

    @abstractmethod
    def search_by_pmid(self, pmid: str) -> IdentifierVerificationResult:
        raise NotImplementedError

    @abstractmethod
    def search_by_doi(self, doi: str) -> IdentifierVerificationResult:
        raise NotImplementedError

    @abstractmethod
    def search_by_title(self, title: str) -> list[IdentifierVerificationResult]:
        raise NotImplementedError
