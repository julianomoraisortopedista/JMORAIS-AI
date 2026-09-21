from __future__ import annotations

import inspect

import pytest
import requests

from jmoraIs.connect import BaseConnector, PubMedConnector
from jmoraIs.scientific_domain import ExistenceVerificationStatus


def test_base_connector_is_abstract() -> None:
    assert inspect.isabstract(BaseConnector)
    with pytest.raises(TypeError):
        BaseConnector()


def test_pubmed_connector_exposes_required_methods() -> None:
    methods = {"search_by_pmid", "search_by_doi", "search_by_title"}
    assert methods.issubset(set(dir(PubMedConnector)))

    for name in sorted(methods):
        method = getattr(PubMedConnector, name)
        params = list(inspect.signature(method).parameters)
        assert params[0] == "self"
        assert len(params) >= 2


class FakeResponse:
    def __init__(self, payload, status_code: int = 200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class FakeHttpClient:
    def __init__(self, response=None, error: Exception | None = None):
        self.response = response
        self.error = error

    def get(self, *args, **kwargs):
        if self.error:
            raise self.error
        return self.response


def test_pubmed_connector_confirms_exact_authoritative_record() -> None:
    payload = {
        "result": {
            "12345678": {
                "uid": "12345678",
                "title": "Authoritative publication",
                "fulljournalname": "Evidence Journal",
                "pubdate": "2025 Jan",
                "authors": [{"name": "Doe J"}],
            },
            "uids": ["12345678"],
        }
    }
    connector = PubMedConnector(http_client=FakeHttpClient(FakeResponse(payload)))

    result = connector.search_by_pmid("12345678")

    assert result.existence_status == ExistenceVerificationStatus.CONFIRMED.value
    assert result.source_name == "NCBI PubMed"
    assert result.source_locator == "https://pubmed.ncbi.nlm.nih.gov/12345678/"
    assert result.authoritative_metadata["title"] == "Authoritative publication"
    assert result.raw_outcome == payload


def test_pubmed_connector_reports_nonexistent_identifier() -> None:
    connector = PubMedConnector(
        http_client=FakeHttpClient(FakeResponse({"result": {"uids": []}}))
    )

    result = connector.search_by_pmid("99999999")

    assert result.existence_status == ExistenceVerificationStatus.NOT_FOUND.value


def test_pubmed_connector_reports_timeout() -> None:
    connector = PubMedConnector(
        http_client=FakeHttpClient(error=requests.Timeout("deterministic timeout"))
    )

    result = connector.search_by_pmid("12345678")

    assert result.existence_status == ExistenceVerificationStatus.TIMEOUT.value
    assert result.raw_outcome == {"error": "deterministic timeout"}


def test_pubmed_connector_reports_invalid_response() -> None:
    connector = PubMedConnector(
        http_client=FakeHttpClient(FakeResponse(ValueError("invalid json")))
    )

    result = connector.search_by_pmid("12345678")

    assert result.existence_status == ExistenceVerificationStatus.INVALID_RESPONSE.value


def test_pubmed_title_search_returns_no_records_for_empty_authoritative_result() -> None:
    connector = PubMedConnector(
        http_client=FakeHttpClient(
            FakeResponse({"esearchresult": {"idlist": []}})
        )
    )

    assert connector.search_by_title("rehabilitation") == []
