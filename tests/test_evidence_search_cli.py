import json

import pytest

from jmoraIs.application.scientific_verification import DiscoveryArticle, ScientificDiscoveryResult
from jmoraIs.connect.pubmed import NCBI_MIN_INTERVAL_SECONDS, PubMedConnector
from scripts import evidence_search


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class RecordingClient:
    def __init__(self):
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        return FakeResponse({"esearchresult": {"idlist": []}})


class FakeClock:
    def __init__(self):
        self.now = 100.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def test_pubmed_search_requests_relevance_ranking():
    client = RecordingClient()
    PubMedConnector(client, min_interval=0).search_by_title("knee arthroplasty")
    assert client.calls[0][1]["sort"] == "relevance"
    assert client.calls[0][1]["term"] == "knee arthroplasty"


def test_pubmed_requests_respect_ncbi_rate_limit():
    clock = FakeClock()
    connector = PubMedConnector(RecordingClient(), monotonic=clock.monotonic, sleep=clock.sleep)
    connector.search_by_title("first")
    connector.search_by_title("second")
    clock.now += 1.0
    connector.search_by_title("third")
    assert clock.sleeps == [pytest.approx(NCBI_MIN_INTERVAL_SECONDS)]


class FakePipeline:
    def __init__(self, result):
        self.result = result
        self.requests = []

    def discover(self, request):
        self.requests.append(request)
        return self.result


RESULT = ScientificDiscoveryResult(
    search_id="search-1",
    articles=(
        DiscoveryArticle("a1", "Total knee replacement trial", "12345678", "10.1/abc", None),
        DiscoveryArticle("a2", "", None, None, None),
    ),
)


def test_discovery_uses_public_boundary_with_query_only():
    pipeline = FakePipeline(RESULT)
    assert evidence_search.discover("knee", pipeline) is RESULT
    (request,) = pipeline.requests
    assert (request.query, request.pmid, request.doi) == ("knee", None, None)


def test_text_output_is_labelled_as_untrusted_candidates():
    text = evidence_search.render_text("knee", RESULT)
    assert evidence_search.NOTICE in text
    assert "PMID 12345678 | DOI 10.1/abc" in text
    assert "https://pubmed.ncbi.nlm.nih.gov/12345678/" in text
    assert "[title unavailable]" in text and "[no identifier]" in text
    assert "supporting" not in text.replace(evidence_search.NOTICE, "")


def test_json_output_never_claims_trusted_evidence():
    payload = json.loads(evidence_search.render_json("knee", RESULT))
    assert payload["trusted_evidence"] is False
    assert payload["notice"] == evidence_search.NOTICE
    assert [c["pmid"] for c in payload["candidates"]] == ["12345678", None]


def test_empty_query_is_rejected(capsys):
    with pytest.raises(SystemExit):
        evidence_search.main(["   "])
