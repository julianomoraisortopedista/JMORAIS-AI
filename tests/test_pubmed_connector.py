from __future__ import annotations

import inspect

import pytest

from jmoraIs.connect import BaseConnector, PubMedConnector


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


def test_pubmed_connector_methods_are_unimplemented_placeholders() -> None:
    connector = PubMedConnector()

    for name in ("search_by_pmid", "search_by_doi"):
        with pytest.raises(NotImplementedError):
            getattr(connector, name)("12345678")

    with pytest.raises(NotImplementedError):
        connector.search_by_title("rehabilitation")
