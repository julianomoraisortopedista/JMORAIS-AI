import os

import pytest

from services.crossref.client import search_crossref
from services.pubmed.client import search_pubmed


pytestmark = pytest.mark.integration


@pytest.mark.skipif(not os.getenv("JMORAIS_ENABLE_EXTERNAL_INTEGRATION"), reason="real external integration tests are disabled by default")
def test_pubmed_live_search_smoke() -> None:
    results = search_pubmed("rehabilitation after arthroplasty", max_results=2)
    assert isinstance(results, list)
    assert len(results) > 0
    assert results[0]["title"]


@pytest.mark.skipif(not os.getenv("JMORAIS_ENABLE_EXTERNAL_INTEGRATION"), reason="real external integration tests are disabled by default")
def test_crossref_live_search_smoke() -> None:
    results = search_crossref("rehabilitation after arthroplasty", max_results=2)
    assert isinstance(results, list)
    assert len(results) > 0
    assert results[0]["title"]
