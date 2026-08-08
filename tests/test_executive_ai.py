from jmoraIs.executive_ai import ExecutiveAI


def test_executive_ai_synthesizes_summary() -> None:
    brief = ExecutiveAI.synthesize(
        title="Postoperative care brief",
        clinical_summary="Evidence supports supervised recovery with close monitoring.",
        evidence=[
            {"pmid": "12345678", "claim_text": "Early mobilization supports recovery."},
            {"doi": "10.1000/rehab", "claim_text": "Progressive rehabilitation improves function."},
        ],
        audit_findings=[{"raw_claim": "The review requires documentation of clinical rationale."}],
        document_summary="The document pack was generated with traceable evidence and cited sources.",
    )

    assert brief.title == "Postoperative care brief"
    assert "evidence-first" in brief.executive_summary.lower()
    assert brief.key_findings
    assert brief.recommendations
    assert brief.evidence_sources
