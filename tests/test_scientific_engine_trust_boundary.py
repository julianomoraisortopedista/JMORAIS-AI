import pytest

from jmoraIs.application.scientific_verification import (
    ScientificDiscoveryResult,
    ScientificVerificationInput,
)
from jmoraIs.scientific_engine import PrePackageEvidenceAccessError, ScientificEvidenceEngine


class StubInternalPipeline:
    def discover(self, _request):
        return ScientificDiscoveryResult(search_id="search-1", articles=())

    def issue_trusted(self, _request, **_kwargs):
        return ("package-sentinel",)


def test_public_discovery_is_explicitly_untrusted():
    engine = ScientificEvidenceEngine(StubInternalPipeline())
    result = engine.discover(ScientificVerificationInput(pmid="12345678"))
    assert result.trusted_evidence is False
    assert not hasattr(result, "eligible_articles")
    assert not hasattr(result, "verification_status")


def test_legacy_verify_cannot_expose_internal_result():
    engine = ScientificEvidenceEngine(StubInternalPipeline())
    with pytest.raises(PrePackageEvidenceAccessError):
        engine.verify(ScientificVerificationInput(pmid="12345678"))
