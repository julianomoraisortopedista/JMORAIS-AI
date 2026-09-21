from __future__ import annotations

from dataclasses import replace

import pytest

from evaluation.scientific_benchmark.dataset import BenchmarkDatasetError, BenchmarkDatasetLoader
from evaluation.scientific_benchmark.metrics import calculate_metrics
from evaluation.scientific_benchmark.models import RecordResult
from evaluation.scientific_benchmark.report import render_json, render_markdown
from evaluation.scientific_benchmark.runner import BenchmarkRunner
from evaluation.scientific_benchmark.validation import (
    find_duplicates,
    normalize_citation,
    normalize_doi,
    reconcile,
    valid_doi,
    valid_pmcid,
    valid_pmid,
    validate_vancouver,
)


@pytest.fixture(scope="module")
def authoritative_dataset():
    return BenchmarkDatasetLoader().load()


def test_loader_reads_versioned_real_literature(authoritative_dataset):
    version, records = authoritative_dataset
    assert version == "authoritative-biomedical-v2.0.0"
    assert len(records) >= 100
    assert all(record.case_type == "REAL_AUTHORITATIVE_CASE" for record in records)
    assert all(record.observations for record in records)
    assert all(item.source_url.startswith("https://") for record in records for item in record.observations)


def test_loader_rejects_unversioned_dataset(tmp_path):
    path = tmp_path / "dataset.json"
    path.write_text('{"schema_version": 1, "records": []}', encoding="utf-8")
    with pytest.raises(BenchmarkDatasetError):
        BenchmarkDatasetLoader(path).load()


@pytest.mark.parametrize("pmid", ["26551272", "32678530", "31535829"])
def test_real_pmids_have_valid_format(pmid):
    assert valid_pmid(pmid)


@pytest.mark.parametrize("pmcid", ["PMC4689591", "PMC7383595", None])
def test_real_pmcids_have_valid_format(pmcid):
    assert valid_pmcid(pmcid)


@pytest.mark.parametrize("doi", [
    "10.1056/NEJMoa1511939", "https://doi.org/10.1056/nejmoa2021436",
    "doi:10.1056/NEJMoa1911303",
])
def test_real_dois_are_normalized_and_validated(doi):
    assert valid_doi(doi)
    assert normalize_doi(doi).startswith("10.1056/")


@pytest.mark.parametrize("value", ["", "0", "PMID:26551272", "26551272x"])
def test_malformed_pmids_are_rejected(value):
    assert not valid_pmid(value)


@pytest.mark.parametrize("value", ["not-a-doi", "11.1056/test", "10/test"])
def test_malformed_dois_are_rejected(value):
    assert not valid_doi(value)


def test_duplicate_detection_uses_authoritative_identity(authoritative_dataset):
    _, records = authoritative_dataset
    duplicate = replace(records[0], record_id="sprint-duplicate")
    assert find_duplicates(records + (duplicate,)) == {"sprint-duplicate": records[0].record_id}


def test_citation_normalization_is_deterministic():
    assert normalize_citation("  A   citation.  ") == "A citation"


def test_vancouver_validation_uses_structured_authoritative_metadata(authoritative_dataset):
    _, records = authoritative_dataset
    assert all(validate_vancouver(record) for record in records)
    assert not validate_vancouver(replace(records[0], vancouver="Wright et al."))


def test_reconciliation_preserves_real_cross_source_disagreement(authoritative_dataset):
    _, records = authoritative_dataset
    record = records[0]
    disagreement = replace(record.observations[0], source="OpenAlex", year=record.year - 1)
    result = reconcile(replace(record, observations=record.observations + (disagreement,)))
    assert result.matched
    assert "year" in result.conflicts
    assert {str(record.year - 1), str(record.year)}.issubset(result.conflicts["year"])
    assert set(result.source_coverage) == {"Crossref", "OpenAlex", "PubMed"}
    assert 0.0 <= result.confidence <= 1.0


def test_runner_calculates_metrics_and_coverage(authoritative_dataset):
    version, records = authoritative_dataset
    report = BenchmarkRunner().run(version, records)
    assert len(report.results) == len(records) >= 100
    assert report.metrics.precision == 1.0
    assert report.metrics.recall == 1.0
    assert report.metrics.false_positive_rate == 0.0
    assert report.metrics.false_negative_rate == 0.0
    assert report.metrics.coverage["PubMed"] == 1.0
    assert report.metrics.coverage["PubMed"] == 1.0
    assert report.metrics.coverage["Crossref"] >= 0.9
    assert report.metrics.coverage["OpenAlex"] >= 0.9


def test_metrics_count_all_confusion_matrix_outcomes(authoritative_dataset):
    version, records = authoritative_dataset
    base = BenchmarkRunner().run(version, records).results[0]
    results: tuple[RecordResult, ...] = (
        replace(base, predicted_match=True, expected_match=True),
        replace(base, predicted_match=False, expected_match=False),
        replace(base, predicted_match=True, expected_match=False),
        replace(base, predicted_match=False, expected_match=True),
    )
    metrics = calculate_metrics(results)
    assert (metrics.true_positive, metrics.true_negative, metrics.false_positive, metrics.false_negative) == (1, 1, 1, 1)
    assert metrics.precision == metrics.recall == 0.5
    assert metrics.false_positive_rate == metrics.false_negative_rate == 0.5


def test_reports_are_machine_and_human_readable(authoritative_dataset):
    version, records = authoritative_dataset
    report = BenchmarkRunner().run(version, records)
    assert '"precision": 1.0' in render_json(report)
    markdown = render_markdown(report)
    assert "# Scientific benchmark authoritative-biomedical-v2.0.0" in markdown
    assert f"| {records[0].record_id} | True | True |" in markdown
