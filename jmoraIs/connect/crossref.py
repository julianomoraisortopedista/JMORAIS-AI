from __future__ import annotations

from typing import Any
from urllib.parse import quote

import requests

from jmoraIs.scientific_domain import (
    ExistenceVerificationStatus,
    IdentifierType,
    IdentifierVerificationResult,
    utc_now,
)

from .base import BaseConnector

CROSSREF_WORKS_URL = "https://api.crossref.org/works"


class CrossrefConnector(BaseConnector):
    """Resolve DOI existence against Crossref's exact works endpoint."""

    def __init__(self, http_client: Any = requests, timeout: float = 20.0):
        self.http_client = http_client
        self.timeout = timeout

    def search_by_doi(self, doi: str) -> IdentifierVerificationResult:
        checked_at = utc_now()
        locator = f"https://doi.org/{doi}"
        try:
            response = self.http_client.get(
                f"{CROSSREF_WORKS_URL}/{quote(doi, safe='')}", timeout=self.timeout
            )
            if response.status_code == 404:
                return IdentifierVerificationResult(
                    identifier_type=IdentifierType.DOI.value,
                    identifier_value=doi,
                    format_valid=True,
                    existence_status=ExistenceVerificationStatus.NOT_FOUND.value,
                    source_name="Crossref",
                    source_locator=locator,
                    checked_at=checked_at,
                    raw_outcome={"status_code": 404},
                )
            response.raise_for_status()
        except requests.Timeout as exc:
            return self._failure(doi, locator, checked_at, ExistenceVerificationStatus.TIMEOUT, exc)
        except requests.RequestException as exc:
            return self._failure(
                doi, locator, checked_at, ExistenceVerificationStatus.SOURCE_UNAVAILABLE, exc
            )

        try:
            payload = response.json()
        except (TypeError, ValueError) as exc:
            return self._failure(
                doi, locator, checked_at, ExistenceVerificationStatus.INVALID_RESPONSE, exc
            )

        message = payload.get("message") if isinstance(payload, dict) else None
        if not isinstance(message, dict) or str(message.get("DOI", "")).lower() != doi.lower():
            return self._failure(
                doi,
                locator,
                checked_at,
                ExistenceVerificationStatus.INVALID_RESPONSE,
                "response DOI does not match request",
                raw_outcome=payload,
            )

        issued = message.get("issued", {}).get("date-parts", [[None]])
        first_date = issued[0] if isinstance(issued, list) and issued else [None]
        year = first_date[0] if isinstance(first_date, list) and first_date and isinstance(first_date[0], int) else None
        title_values = message.get("title") or []
        journal_values = message.get("container-title") or []
        authors = []
        for author in message.get("author") or []:
            if not isinstance(author, dict):
                continue
            name = f"{author.get('given') or ''} {author.get('family') or ''}".strip()
            if name:
                authors.append(name)
        metadata = {
            "doi": doi,
            "title": title_values[0] if isinstance(title_values, list) and title_values else None,
            "journal": journal_values[0] if isinstance(journal_values, list) and journal_values else None,
            "year": year,
            "authors": authors,
        }
        return IdentifierVerificationResult(
            identifier_type=IdentifierType.DOI.value,
            identifier_value=doi,
            format_valid=True,
            existence_status=ExistenceVerificationStatus.CONFIRMED.value,
            source_name="Crossref",
            source_locator=locator,
            checked_at=checked_at,
            raw_outcome=payload,
            authoritative_metadata=metadata,
        )

    def search_by_pmid(self, pmid: str) -> IdentifierVerificationResult:
        return IdentifierVerificationResult(
            identifier_type=IdentifierType.PMID.value,
            identifier_value=pmid,
            format_valid=True,
            existence_status=ExistenceVerificationStatus.NOT_CHECKED.value,
            source_name="Crossref",
            checked_at=utc_now(),
            raw_outcome={"reason": "PMID existence is verified by NCBI PubMed"},
            error_code="UNSUPPORTED_IDENTIFIER",
        )

    def search_by_title(self, title: str) -> list[IdentifierVerificationResult]:
        raise NotImplementedError

    @staticmethod
    def _failure(
        doi: str,
        locator: str,
        checked_at: Any,
        status: ExistenceVerificationStatus,
        error: Any,
        raw_outcome: Any = None,
    ) -> IdentifierVerificationResult:
        return IdentifierVerificationResult(
            identifier_type=IdentifierType.DOI.value,
            identifier_value=doi,
            format_valid=True,
            existence_status=status.value,
            source_name="Crossref",
            source_locator=locator,
            checked_at=checked_at,
            raw_outcome=raw_outcome if raw_outcome is not None else {"error": str(error)},
            error_code=status.value,
        )
