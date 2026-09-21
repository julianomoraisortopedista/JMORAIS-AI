from __future__ import annotations

import requests

from jmoraIs.connect import CrossrefConnector
from jmoraIs.scientific_domain import ExistenceVerificationStatus


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


def test_crossref_connector_confirms_exact_doi() -> None:
    payload = {
        "message": {
            "DOI": "10.1234/existing",
            "title": ["Authoritative publication"],
            "container-title": ["Evidence Journal"],
            "issued": {"date-parts": [[2025]]},
            "author": [{"given": "Jane", "family": "Doe"}],
        }
    }
    connector = CrossrefConnector(http_client=FakeHttpClient(FakeResponse(payload)))

    result = connector.search_by_doi("10.1234/existing")

    assert result.existence_status == ExistenceVerificationStatus.CONFIRMED.value
    assert result.source_name == "Crossref"
    assert result.source_locator == "https://doi.org/10.1234/existing"
    assert result.authoritative_metadata["title"] == "Authoritative publication"
    assert result.raw_outcome == payload


def test_crossref_connector_reports_nonexistent_doi() -> None:
    connector = CrossrefConnector(
        http_client=FakeHttpClient(FakeResponse({}, status_code=404))
    )

    result = connector.search_by_doi("10.1234/missing")

    assert result.existence_status == ExistenceVerificationStatus.NOT_FOUND.value
    assert result.raw_outcome == {"status_code": 404}


def test_crossref_connector_reports_timeout() -> None:
    connector = CrossrefConnector(
        http_client=FakeHttpClient(error=requests.Timeout("deterministic timeout"))
    )

    result = connector.search_by_doi("10.1234/existing")

    assert result.existence_status == ExistenceVerificationStatus.TIMEOUT.value
    assert result.raw_outcome == {"error": "deterministic timeout"}


def test_crossref_connector_rejects_mismatched_response() -> None:
    connector = CrossrefConnector(
        http_client=FakeHttpClient(
            FakeResponse({"message": {"DOI": "10.9999/different"}})
        )
    )

    result = connector.search_by_doi("10.1234/requested")

    assert result.existence_status == ExistenceVerificationStatus.INVALID_RESPONSE.value
    assert result.raw_outcome == {"message": {"DOI": "10.9999/different"}}
