from __future__ import annotations

import pytest
from dataclasses import replace

from jmoraIs.application import ScientificEvidencePackagePort
from jmoraIs.clinical import DeprecatedClinicalPathError
from jmoraIs.clinical.application import ClinicalIntelligenceService
from jmoraIs.evidence_ledger import AppendOnlyEvidenceLedger, hash_payload
from jmoraIs.infrastructure import InMemoryPackageCatalogRepository
from tests.test_evidence_package_boundary import NOW, verified_article


def package_port():
    return ScientificEvidencePackagePort(
        catalog=InMemoryPackageCatalogRepository(), clock=lambda: NOW,
    )


def issue_direction(port, direction: str, suffix: str):
    article = verified_article()
    article.article_id = f"article-{suffix}"
    article.provenance = replace(article.provenance, source_id=f"provenance-{suffix}")
    ledger = AppendOnlyEvidenceLedger()
    claim = ledger.create_claim(
        f"Recommendation evidence {suffix}", claim_id=f"claim-{suffix}", created_at=NOW,
    )
    _, support, _ = ledger.register_evidence(
        claim_id=claim.claim_id, source_name="NCBI PubMed", source_type="pubmed",
        passage=f"Verified evidence {suffix}.", pmid=article.pmid,
        payload_hash=hash_payload({"pmid": article.pmid, "suffix": suffix}),
        retrieved_at=NOW, verification_version="ST-02", pipeline_version="ST-12",
        policy_version="ST-02", support_direction=direction, occurred_at=NOW,
    )
    return port.issue(
        article=article, ledger=ledger, claim_id=claim.claim_id,
        support_ids=(support.support_id,), pipeline_version="ST-12",
    )


def test_st12_raw_package_service_is_permanently_fail_closed():
    with pytest.raises(DeprecatedClinicalPathError, match="governed"):
        ClinicalIntelligenceService(package_port(), object(), clock=lambda: NOW)
