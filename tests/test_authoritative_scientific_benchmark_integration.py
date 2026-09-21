from __future__ import annotations

import os

import pytest

from evaluation.scientific_benchmark.dataset import BenchmarkDatasetLoader
from evaluation.scientific_benchmark.sources import AuthoritativeClients, AuthoritativeSourceError
from evaluation.scientific_benchmark.validation import normalize_doi, normalize_text

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("JMORAIS_RUN_AUTHORITATIVE_BENCHMARK") != "1",
        reason="set JMORAIS_RUN_AUTHORITATIVE_BENCHMARK=1 for live authoritative APIs",
    ),
]


@pytest.fixture(scope="module")
def clients():
    return AuthoritativeClients(timeout=30)


@pytest.fixture(scope="module")
def records():
    return BenchmarkDatasetLoader().load()[1]


@pytest.mark.parametrize("record_index", [0, 1, 2])
def test_pubmed_crossref_and_openalex_confirm_real_publication(clients, records, record_index):
    record = records[record_index]
    pubmed = clients.pubmed(record.pmid)
    crossref = clients.crossref(record.doi)
    openalex = clients.openalex(record.doi)
    article_ids = {item["idtype"]: item["value"] for item in pubmed["articleids"]}
    assert normalize_doi(article_ids["doi"]) == normalize_doi(record.doi)
    assert normalize_doi(crossref["DOI"]) == normalize_doi(record.doi)
    assert normalize_text(openalex["title"]) == normalize_text(record.title)


@pytest.mark.parametrize("record_index", [0, 1])
def test_pmc_confirms_real_pmc_identifier(clients, records, record_index):
    record = records[record_index]
    result = clients.pmc(record.pmcid)
    assert str(result["pmid"]) == record.pmid
    assert normalize_doi(result["doi"]) == normalize_doi(record.doi)


def test_semantic_scholar_is_used_when_available(clients, records):
    record = records[0]
    try:
        result = clients.semantic_scholar(record.doi)
    except AuthoritativeSourceError as exc:
        pytest.skip(f"Semantic Scholar unavailable: {exc}")
    assert normalize_text(result["title"]) == normalize_text(record.title)
    assert normalize_doi(result["externalIds"]["DOI"]) == normalize_doi(record.doi)
