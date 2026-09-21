import pytest

from jmoraIs.clinical import DeprecatedClinicalPathError
from jmoraIs.clinical.application import ClinicalIntelligenceService
from tests.test_clinical_intelligence_foundation import package_port


def test_legacy_integration_cannot_bypass_governed_evidence():
    with pytest.raises(DeprecatedClinicalPathError):
        ClinicalIntelligenceService(package_port(), object())
