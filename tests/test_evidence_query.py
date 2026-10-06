import argparse

import pytest
import requests

from jmoraIs.application.evidence_query import (
    BuiltEvidenceQuery, EvidenceQueryRejected, MeshExpansion, PICOQuestion, build_pubmed_query,
)
from jmoraIs.connect.pubmed import PubMedConnector
from scripts import evidence_search

MESH = {"knee osteoarthritis": ("osteoarthritis, knee",),
        "total knee arthroplasty": ("arthroplasty, replacement, knee",),
        "total knee replacement": ("arthroplasty, replacement, knee",)}


def question(**overrides):
    values = dict(population=("knee osteoarthritis",),
                  intervention=("total knee arthroplasty", "total knee replacement"),
                  comparison=("nonoperative",), designs=("rct", "sr"))
    values.update(overrides)
    return PICOQuestion(**values)


def test_concepts_are_or_groups_joined_by_and_with_design_filters():
    built = build_pubmed_query(question(), lambda term: MESH.get(term, ()))
    assert built.query == (
        '("osteoarthritis, knee"[MeSH Terms] OR "knee osteoarthritis"[tiab]) AND '
        '("arthroplasty, replacement, knee"[MeSH Terms] OR "total knee arthroplasty"[tiab] '
        'OR "total knee replacement"[tiab]) AND ("nonoperative"[tiab]) AND '
        '(randomized controlled trial[pt] OR systematic review[pt])')


def test_every_mesh_heading_is_traceable_to_its_synonym_once():
    built = build_pubmed_query(question(), lambda term: MESH.get(term, ()))
    assert built.expansions == (
        MeshExpansion("population", "knee osteoarthritis", "osteoarthritis, knee"),
        MeshExpansion("intervention", "total knee arthroplasty", "arthroplasty, replacement, knee"),
    )


def test_without_lookup_only_free_text_is_used():
    built = build_pubmed_query(question(designs=()))
    assert "[MeSH Terms]" not in built.query and built.expansions == ()
    assert "[pt]" not in built.query


@pytest.mark.parametrize("term", ['knee" OR "x', "knee[tiab]", "knee AND hip", "*", "", "  ", "(knee)"])
def test_query_syntax_cannot_be_injected(term):
    with pytest.raises(EvidenceQueryRejected):
        question(population=(term,))


def test_required_elements_and_known_designs():
    with pytest.raises(EvidenceQueryRejected):
        question(population=())
    with pytest.raises(EvidenceQueryRejected):
        question(intervention=())
    with pytest.raises(EvidenceQueryRejected):
        question(designs=("case-report",))
    with pytest.raises(EvidenceQueryRejected):
        build_pubmed_query("knee")


def test_accented_and_hyphenated_terms_are_accepted():
    built = build_pubmed_query(question(population=("artrose de joelho",), comparison=("non-surgical",)))
    assert '"artrose de joelho"[tiab]' in built.query and '"non-surgical"[tiab]' in built.query


class FakeResponse:
    def __init__(self, payload, error=None):
        self.payload, self.error = payload, error

    def raise_for_status(self):
        if self.error:
            raise self.error

    def json(self):
        return self.payload


class Client:
    def __init__(self, response):
        self.response = response

    def get(self, url, params=None, timeout=None):
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def connector(response):
    return PubMedConnector(Client(response), min_interval=0)


def test_mesh_lookup_accepts_only_whole_phrase_mappings():
    payload = {"esearchresult": {"translationset": [
        {"from": "Knee  Osteoarthritis", "to": '"osteoarthritis, knee"[MeSH Terms] OR "knee"[All Fields]'},
        {"from": "treatment", "to": '"therapeutics"[MeSH Terms] OR "treatment"[All Fields]'},
    ]}}
    assert connector(FakeResponse(payload)).mesh_headings_for("knee osteoarthritis") == ("osteoarthritis, knee",)
    assert connector(FakeResponse(payload)).mesh_headings_for("nonoperative treatment") == ()


@pytest.mark.parametrize("response", [
    requests.Timeout("slow"), requests.ConnectionError("down"),
    FakeResponse({}, None), FakeResponse({"esearchresult": {"translationset": "bad"}}),
    FakeResponse({}, requests.HTTPError("429")),
])
def test_mesh_lookup_fails_closed_to_free_text(response):
    assert connector(response).mesh_headings_for("knee osteoarthritis") == ()


def args(**values):
    base = dict(query=None, population=None, intervention=None, comparison=None, outcome=None, design=None, no_mesh=False)
    base.update(values)
    return argparse.Namespace(**base)


class StubPubMed:
    def mesh_headings_for(self, term):
        return MESH.get(term, ())


def test_cli_builds_pico_query_with_semicolon_synonyms():
    built = evidence_search.build_query(args(population="knee osteoarthritis", intervention="total knee arthroplasty; total knee replacement",
                                             design="rct"), StubPubMed())
    assert '"total knee replacement"[tiab]' in built.query and built.query.endswith("(randomized controlled trial[pt])")
    assert built.expansions[0].mesh_heading == "osteoarthritis, knee"


def test_cli_no_mesh_and_mode_conflicts():
    built = evidence_search.build_query(args(population="knee osteoarthritis", intervention="tka", no_mesh=True), StubPubMed())
    assert "[MeSH Terms]" not in built.query
    assert evidence_search.build_query(args(query=" free text ")) == BuiltEvidenceQuery("free text")
    with pytest.raises(EvidenceQueryRejected):
        evidence_search.build_query(args(query="x", population="y", intervention="z"))
    with pytest.raises(EvidenceQueryRejected):
        evidence_search.build_query(args())


def test_text_output_lists_mesh_provenance():
    built = BuiltEvidenceQuery("q", (MeshExpansion("population", "knee osteoarthritis", "osteoarthritis, knee"),))
    from tests.test_evidence_search_cli import RESULT
    text = evidence_search.render_text("q", RESULT, built)
    assert "MeSH: population 'knee osteoarthritis' -> osteoarthritis, knee" in text


def test_recency_window_adds_publication_date_filter():
    built = build_pubmed_query(question(designs=(), from_year=2022))
    assert built.query.endswith('AND ("2022/01/01"[dp] : "3000"[dp])')
    with pytest.raises(EvidenceQueryRejected):
        question(from_year=1500)
