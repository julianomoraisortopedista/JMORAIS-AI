from __future__ import annotations

from dataclasses import replace
import time
from typing import Any, Callable

import requests

from .base import BaseConnector
from jmoraIs.scientific_domain import (
    ExistenceVerificationStatus,
    IdentifierType,
    IdentifierVerificationResult,
    utc_now,
)

PUBMED_SUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
PUBMED_SEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
# NCBI E-utilities allow 3 requests/second without an API key.
NCBI_MIN_INTERVAL_SECONDS = 0.34


class PubMedConnector(BaseConnector):
    """Resolve publication existence against the authoritative NCBI PubMed API."""

    def __init__(
        self,
        http_client: Any = requests,
        timeout: float = 20.0,
        *,
        min_interval: float = NCBI_MIN_INTERVAL_SECONDS,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.http_client = http_client
        self.timeout = timeout
        self._min_interval = min_interval
        self._monotonic = monotonic
        self._sleep = sleep
        self._last_request_at: float | None = None

    def _get(self, url: str, **kwargs: Any) -> Any:
        if self._last_request_at is not None:
            wait = self._min_interval - (self._monotonic() - self._last_request_at)
            if wait > 0:
                self._sleep(wait)
        try:
            return self.http_client.get(url, **kwargs)
        finally:
            self._last_request_at = self._monotonic()

    def search_by_pmid(self, pmid: str) -> IdentifierVerificationResult:
        checked_at = utc_now()
        locator = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
        try:
            response = self._get(
                PUBMED_SUMMARY_URL,
                params={"db": "pubmed", "id": pmid, "retmode": "json"},
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.Timeout as exc:
            return self._failure(pmid, locator, checked_at, ExistenceVerificationStatus.TIMEOUT, exc)
        except requests.RequestException as exc:
            return self._failure(
                pmid, locator, checked_at, ExistenceVerificationStatus.SOURCE_UNAVAILABLE, exc
            )

        try:
            payload = response.json()
        except (TypeError, ValueError) as exc:
            return self._failure(
                pmid, locator, checked_at, ExistenceVerificationStatus.INVALID_RESPONSE, exc
            )

        if not isinstance(payload, dict) or not isinstance(payload.get("result"), dict):
            return self._failure(
                pmid,
                locator,
                checked_at,
                ExistenceVerificationStatus.INVALID_RESPONSE,
                "missing result object",
                raw_outcome=payload,
            )

        record = payload["result"].get(pmid)
        if not isinstance(record, dict) or str(record.get("uid", "")) != pmid:
            return IdentifierVerificationResult(
                identifier_type=IdentifierType.PMID.value,
                identifier_value=pmid,
                format_valid=True,
                existence_status=ExistenceVerificationStatus.NOT_FOUND.value,
                source_name="NCBI PubMed",
                source_locator=locator,
                checked_at=checked_at,
                raw_outcome=payload,
            )

        authors = [
            str(author.get("name", "")).strip()
            for author in record.get("authors", [])
            if isinstance(author, dict) and str(author.get("name", "")).strip()
        ]
        pubdate = record.get("pubdate")
        year = int(pubdate[:4]) if isinstance(pubdate, str) and pubdate[:4].isdigit() else None
        doi = None
        for article_id in record.get("articleids") or []:
            if isinstance(article_id, dict) and str(article_id.get("idtype", "")).lower() == "doi":
                doi = str(article_id.get("value") or "").strip() or None
                break
        metadata = {
            "pmid": pmid,
            "doi": doi,
            "title": record.get("title") or None,
            "journal": record.get("fulljournalname") or record.get("source") or None,
            "year": year,
            "authors": authors,
        }
        return IdentifierVerificationResult(
            identifier_type=IdentifierType.PMID.value,
            identifier_value=pmid,
            format_valid=True,
            existence_status=ExistenceVerificationStatus.CONFIRMED.value,
            source_name="NCBI PubMed",
            source_locator=locator,
            checked_at=checked_at,
            raw_outcome=payload,
            authoritative_metadata=metadata,
        )

    def search_by_doi(self, doi: str) -> IdentifierVerificationResult:
        ids_or_error = self._search_ids(f'"{doi}"[AID]', requested_identifier=doi, identifier_type=IdentifierType.DOI)
        if isinstance(ids_or_error, IdentifierVerificationResult):
            return ids_or_error
        if not ids_or_error:
            return IdentifierVerificationResult(
                identifier_type=IdentifierType.DOI.value,
                identifier_value=doi,
                format_valid=True,
                existence_status=ExistenceVerificationStatus.NOT_FOUND.value,
                source_name="NCBI PubMed",
                source_locator=f"https://doi.org/{doi}",
                checked_at=utc_now(),
                raw_outcome={"idlist": []},
            )
        result = self.search_by_pmid(ids_or_error[0])
        if result.authoritative_metadata is not None and not result.authoritative_metadata.get("doi"):
            result = replace(
                result,
                authoritative_metadata={**result.authoritative_metadata, "doi": doi},
            )
        return result

    def search_by_title(self, title: str) -> list[IdentifierVerificationResult]:
        ids_or_error = self._search_ids(title, requested_identifier=title, identifier_type=IdentifierType.PMID)
        if isinstance(ids_or_error, IdentifierVerificationResult):
            return [ids_or_error]
        return [self.search_by_pmid(pmid) for pmid in ids_or_error]

    def _search_ids(
        self,
        term: str,
        *,
        requested_identifier: str,
        identifier_type: IdentifierType,
        max_results: int = 20,
    ) -> list[str] | IdentifierVerificationResult:
        checked_at = utc_now()
        try:
            response = self._get(
                PUBMED_SEARCH_URL,
                params={
                    "db": "pubmed",
                    "term": term,
                    "retmode": "json",
                    "retmax": str(max_results),
                    "sort": "relevance",
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.Timeout as exc:
            return IdentifierVerificationResult(
                identifier_type=identifier_type.value,
                identifier_value=requested_identifier,
                format_valid=True,
                existence_status=ExistenceVerificationStatus.TIMEOUT.value,
                source_name="NCBI PubMed",
                checked_at=checked_at,
                raw_outcome={"error": str(exc)},
                error_code=ExistenceVerificationStatus.TIMEOUT.value,
            )
        except requests.RequestException as exc:
            return IdentifierVerificationResult(
                identifier_type=identifier_type.value,
                identifier_value=requested_identifier,
                format_valid=True,
                existence_status=ExistenceVerificationStatus.SOURCE_UNAVAILABLE.value,
                source_name="NCBI PubMed",
                checked_at=checked_at,
                raw_outcome={"error": str(exc)},
                error_code=ExistenceVerificationStatus.SOURCE_UNAVAILABLE.value,
            )
        try:
            payload = response.json()
            ids = payload["esearchresult"]["idlist"]
            if not isinstance(ids, list) or not all(isinstance(value, str) for value in ids):
                raise TypeError("idlist must be a list of strings")
            return ids
        except (KeyError, TypeError, ValueError) as exc:
            return IdentifierVerificationResult(
                identifier_type=identifier_type.value,
                identifier_value=requested_identifier,
                format_valid=True,
                existence_status=ExistenceVerificationStatus.INVALID_RESPONSE.value,
                source_name="NCBI PubMed",
                checked_at=checked_at,
                raw_outcome=locals().get("payload", {"error": str(exc)}),
                error_code=ExistenceVerificationStatus.INVALID_RESPONSE.value,
            )

    @staticmethod
    def _failure(
        pmid: str,
        locator: str,
        checked_at: Any,
        status: ExistenceVerificationStatus,
        error: Any,
        raw_outcome: Any = None,
    ) -> IdentifierVerificationResult:
        return IdentifierVerificationResult(
            identifier_type=IdentifierType.PMID.value,
            identifier_value=pmid,
            format_valid=True,
            existence_status=status.value,
            source_name="NCBI PubMed",
            source_locator=locator,
            checked_at=checked_at,
            raw_outcome=raw_outcome if raw_outcome is not None else {"error": str(error)},
            error_code=status.value,
        )
