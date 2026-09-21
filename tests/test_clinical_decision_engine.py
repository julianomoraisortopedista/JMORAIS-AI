import pytest

from jmoraIs.application import ScientificEvidencePackagePort
from jmoraIs.clinical import DeprecatedClinicalPathError
from jmoraIs.clinical_engine import ClinicalDecisionEngine
from jmoraIs.infrastructure import InMemoryPackageCatalogRepository
from tests.test_evidence_package_boundary import NOW, issue


def new_port():
    return ScientificEvidencePackagePort(
        catalog=InMemoryPackageCatalogRepository(), clock=lambda: NOW,
    )


def test_legacy_clinical_engine_is_permanently_fail_closed():
    with pytest.raises(DeprecatedClinicalPathError, match="governed"):
        ClinicalDecisionEngine(new_port())


def test_valid_raw_evidence_package_cannot_restore_legacy_path():
    port = new_port()
    issue(port)
    with pytest.raises(DeprecatedClinicalPathError):
        ClinicalDecisionEngine(port)
