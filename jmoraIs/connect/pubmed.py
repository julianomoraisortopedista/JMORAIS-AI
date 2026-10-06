from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from hashlib import sha256
import re
import time
from xml.etree import ElementTree
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
PUBMED_FETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
# NCBI E-utilities allow 3 requests/second without an API key.
NCBI_MIN_INTERVAL_SECONDS = 0.34
_MESH_CLAUSE = re.compile(r'"([A-Za-z0-9][A-Za-z0-9 ,\-\']*)"\[MeSH Terms\]')


class AbstractUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class PublishedAbstract:
    """Exact abstract text as published in PubMed; public bibliographic data only."""
    pmid: str
    title: str
    text: str
    source_locator: str
    retrieved_at: datetime
    content_hash: str


def parse_pubmed_abstract(pmid: str, xml_text: str, retrieved_at: datetime) -> PublishedAbstract:
    # PubMed sends an external-DTD DOCTYPE; internal subsets/entities are refused.
    if "<!ENTITY" in xml_text or re.search(r"<!DOCTYPE[^>]*\[", xml_text):
        raise AbstractUnavailable("unsafe XML declaration")
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as exc:
        raise AbstractUnavailable("invalid PubMed XML") from exc
    article = next((a for a in root.iter("PubmedArticle")
                    if (a.findtext("MedlineCitation/PMID") or "").strip() == pmid), None)
    if article is None:
        raise AbstractUnavailable("PMID absent from PubMed response")
    title = " ".join("".join(article.find("MedlineCitation/Article/ArticleTitle").itertext()).split()) \
        if article.find("MedlineCitation/Article/ArticleTitle") is not None else ""
    sections = []
    for node in article.iter("AbstractText"):
        text = " ".join("".join(node.itertext()).split())
        if text:
            label = node.get("Label")
            sections.append(f"{label}: {text}" if label else text)
    if not sections:
        raise AbstractUnavailable("no abstract published for this PMID")
    text = "\n".join(sections)
    return PublishedAbstract(pmid, title, text, f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                             retrieved_at, sha256(text.encode("utf-8")).hexdigest())


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
        search_limit: int = 20,
    ):
        self.http_client = http_client
        self.timeout = timeout
        self._min_interval = min_interval
        self._monotonic = monotonic
        self._sleep = sleep
        self._last_request_at: float | None = None
        self._search_limit = max(1, min(int(search_limit), 100))

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
            "journal_abbreviation": str(record.get("source") or "").strip() or None,
            "volume": str(record.get("volume") or "").strip() or None,
            "issue": str(record.get("issue") or "").strip() or None,
            "pages": str(record.get("pages") or "").strip() or None,
            "publication_types": [str(v) for v in record.get("pubtype") or [] if isinstance(v, str) and v.strip()],
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

    def fetch_abstract(self, pmid: str) -> PublishedAbstract:
        if not re.fullmatch(r"[1-9][0-9]{0,8}", pmid or ""):
            raise AbstractUnavailable("malformed PMID")
        try:
            response = self._get(PUBMED_FETCH_URL, params={"db": "pubmed", "id": pmid, "retmode": "xml"},
                                 timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise AbstractUnavailable("PubMed unavailable") from exc
        return parse_pubmed_abstract(pmid, response.text, utc_now())

    def mesh_headings_for(self, phrase: str) -> tuple[str, ...]:
        """MeSH headings PubMed maps to the whole phrase; empty on any failure."""
        try:
            response = self._get(
                PUBMED_SEARCH_URL,
                params={"db": "pubmed", "term": phrase, "retmode": "json", "retmax": "0"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            translations = response.json()["esearchresult"].get("translationset") or []
        except (requests.RequestException, KeyError, TypeError, ValueError):
            return ()
        wanted = " ".join(phrase.casefold().split())
        headings: list[str] = []
        for item in translations:
            if not isinstance(item, dict) or " ".join(str(item.get("from", "")).casefold().split()) != wanted:
                continue
            for heading in (value.casefold() for value in _MESH_CLAUSE.findall(str(item.get("to", "")))):
                if heading not in headings:
                    headings.append(heading)
        return tuple(headings)

    def search_by_title(self, title: str) -> list[IdentifierVerificationResult]:
        ids_or_error = self._search_ids(title, requested_identifier=title, identifier_type=IdentifierType.PMID,
                                        max_results=self._search_limit)
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
