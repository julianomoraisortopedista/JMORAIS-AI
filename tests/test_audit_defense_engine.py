from jmoraIs.audit_engine import AuditDefenseEngine


def test_parse_claims_extracts_atomic_claims() -> None:
    text = "The device was used for rehabilitation. Early mobilization improves outcomes. The patient was monitored closely."

    claims = AuditDefenseEngine.parse_claims(text)

    assert len(claims) >= 2
    assert claims[0].claim_id.startswith("claim-")
    assert claims[0].category in {"medical", "general"}


def test_build_evidence_matrix_and_generate_response() -> None:
    claims = AuditDefenseEngine.parse_claims("The procedure was clinically justified. The patient underwent a monitored protocol.")
    evidence = [
        {
            "claim_text": "The procedure was clinically justified and supported by evidence.",
            "support_direction": "supporting",
            "pmid": "11111111",
            "verification_status": "VERIFIED",
            "confidence": 0.9,
        },
        {
            "claim_text": "There are concerns about the generalizability of the evidence.",
            "support_direction": "neutral",
            "doi": "10.1000/audit",
            "verification_status": "PARTIALLY_VERIFIED",
            "confidence": 0.5,
        },
    ]

    matrix = AuditDefenseEngine.build_evidence_matrix(claims, evidence)
    response = AuditDefenseEngine.generate_defense_response(claims[0], matrix[0], evidence)

    assert matrix[0].assessed_status in {"supported", "needs_review"}
    assert response.claim_id == claims[0].claim_id
    assert response.confidence > 0.0
    assert response.cited_sources
