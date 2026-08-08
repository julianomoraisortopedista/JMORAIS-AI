from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from jmoraIs.clinical_engine import ClinicalCase, ClinicalDecisionEngine
from jmoraIs.db import Base, ClinicalDecision, store_clinical_decision


def test_clinical_decision_engine_generates_supportive_recommendation() -> None:
    case = ClinicalCase(
        condition="postoperative knee rehabilitation",
        symptoms=["pain", "limited range of motion"],
        risk_factors=["older age"],
        contraindications=["active infection"],
    )
    evidence = [
        {
            "claim_text": "Early mobilization after arthroplasty improves recovery outcomes.",
            "verification_status": "VERIFIED",
            "support_direction": "supporting",
            "confidence": 0.94,
            "pmid": "12345678",
        },
        {
            "claim_text": "Progressive rehabilitation reduces stiffness after knee surgery.",
            "verification_status": "PARTIALLY_VERIFIED",
            "support_direction": "supporting",
            "confidence": 0.78,
            "doi": "10.1000/rehab",
        },
    ]

    recommendation = ClinicalDecisionEngine.assess(case, evidence)

    assert recommendation.evidence_strength in {"strong", "moderate"}
    assert "supervised" in recommendation.recommendation.lower()
    assert "active infection" in recommendation.caution
    assert recommendation.source_ids


def test_clinical_decision_engine_persists_decision() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)

    case = ClinicalCase(
        condition="spinal pain management",
        symptoms=["low back pain"],
        contraindications=["pregnancy"],
    )
    evidence = [
        {
            "claim_text": "Non-pharmacologic strategies may improve function in chronic low back pain.",
            "verification_status": "VERIFIED",
            "support_direction": "supporting",
            "confidence": 0.8,
            "pmid": "56789012",
        }
    ]

    with Session(engine) as session:
        result = ClinicalDecisionEngine.assess(case, evidence)
        stored = store_clinical_decision(result, session)
        assert stored.condition == "spinal pain management"
        assert session.query(ClinicalDecision).count() == 1
        assert "pregnancy" in stored.caution
