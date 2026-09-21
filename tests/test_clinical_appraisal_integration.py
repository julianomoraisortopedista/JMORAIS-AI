from __future__ import annotations

from datetime import date

import pytest

from jmoraIs.appraisal import (
    ApplicabilityContext,
    AppraisalEvidenceRejected,
    ClinicalAppraisalService,
    EvidenceLevel,
    RecommendationStrength,
    RecommendationValidity,
)
from tests.test_clinical_appraisal_domain import TODAY, guideline, quality, request
from tests.test_clinical_intelligence_foundation import issue_direction, package_port


def test_valid_evidence_package_produces_traceable_explainable_appraisal():
    port = package_port()
    package = issue_direction(port, "supporting", "appraisal")
    service = ClinicalAppraisalService(port)
    appraised, resolution = service.assess((request(
        package_id=package.package_id,
        contexts=(ApplicabilityContext.ADULT, ApplicabilityContext.OUTPATIENT),
        assessment=quality(limitations=("Single primary outcome.",)),
    ),), as_of=TODAY)
    result = appraised[0]
    assert result.recommendation_validity == RecommendationValidity.VALID
    assert result.eligible_for_clinical_intelligence
    assert result.provenance_references == package.provenance_references
    assert result.ledger_references == package.ledger_references
    assert result.policy_version == package.policy_version
    assert result.explainability.evidence_level == EvidenceLevel.RANDOMIZED_CONTROLLED_TRIAL
    assert result.explainability.recommendation_strength == RecommendationStrength.STRONG_FOR
    assert result.explainability.guideline_authority == "Society A"
    assert result.explainability.applicability == (
        ApplicabilityContext.ADULT, ApplicabilityContext.OUTPATIENT,
    )
    assert result.explainability.limitations == ("Single primary outcome.",)
    assert resolution.conflicts == ()


@pytest.mark.parametrize("governance,expected", [
    (guideline(expires=date(2025, 1, 1)), RecommendationValidity.EXPIRED_GUIDELINE),
    (guideline(superseded="guideline-2"), RecommendationValidity.SUPERSEDED_RECOMMENDATION),
    (guideline(withdrawn=date(2025, 1, 1)), RecommendationValidity.WITHDRAWN_RECOMMENDATION),
])
def test_non_current_recommendations_are_explained_but_not_eligible(governance, expected):
    port = package_port()
    package = issue_direction(port, "supporting", expected.value)
    service = ClinicalAppraisalService(port)
    result = service.assess((request(package_id=package.package_id, governance=governance),),
                            as_of=TODAY)[0][0]
    assert result.recommendation_validity == expected
    assert not result.eligible_for_clinical_intelligence
    assert expected.value in result.explainability.limitations[-1]


def test_conflicts_are_exposed_and_block_automatic_clinical_eligibility():
    port = package_port()
    supporting = issue_direction(port, "supporting", "guideline-for")
    opposing = issue_direction(port, "opposing", "guideline-against")
    requests = (
        request("for", package_id=supporting.package_id),
        request("against", package_id=opposing.package_id,
                strength=RecommendationStrength.STRONG_AGAINST,
                governance=guideline("guideline-2", "Society B", date(2024, 1, 1))),
    )
    appraised, resolution = ClinicalAppraisalService(port).assess(requests, as_of=TODAY)
    assert len(resolution.conflicts) == 3
    assert all(not item.eligible_for_clinical_intelligence for item in appraised)
    assert all(item.explainability.conflicts_detected for item in appraised)
    assert all("human resolution" in item.explainability.limitations[-1] for item in appraised)


def test_raw_or_forged_evidence_cannot_cross_appraisal_boundary():
    class ForgedPort:
        def get(self, package_id):
            return {"verification_status": "VERIFIED"}

    with pytest.raises(AppraisalEvidenceRejected):
        ClinicalAppraisalService(ForgedPort()).assess((request(),), as_of=TODAY)


def test_missing_or_revoked_package_fails_closed():
    with pytest.raises(AppraisalEvidenceRejected):
        ClinicalAppraisalService(package_port()).assess((request(package_id="missing"),), as_of=TODAY)
