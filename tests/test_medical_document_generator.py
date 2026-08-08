from jmoraIs.document_generator import MedicalDocumentGenerator


def test_build_summary_and_evidence_pack() -> None:
    summary = MedicalDocumentGenerator.build_summary(
        "Rehabilitation summary",
        "Postoperative knee rehabilitation",
        ["Early mobilization", "Progressive strengthening"],
    )

    document = MedicalDocumentGenerator.build_evidence_pack(
        "Evidence pack",
        summary,
        [
            {"claim_text": "Early mobilization improves recovery.", "pmid": "12345678"},
            {"claim_text": "Exercise therapy reduces stiffness.", "doi": "10.1000/rehab"},
        ],
    )

    assert "Rehabilitation summary" in summary
    assert document.title == "Evidence pack"
    assert len(document.references) == 2
    assert document.sections[1]["content"]


def test_build_clinical_report() -> None:
    result = MedicalDocumentGenerator.build_clinical_report(
        "Clinical report",
        "Patient with post-op mobility limitation",
        {
            "recommendation": "Evidence supports supervised rehabilitation.",
            "caution": ["active infection", "severe pain"],
            "evidence_strength": "moderate",
            "source_ids": ["12345678", "10.1000/rehab"],
        },
    )

    assert result.title == "Clinical report"
    assert "supervised rehabilitation" in result.summary.lower()
    assert "active infection" in result.sections[2]["content"]
    assert len(result.references) == 2
