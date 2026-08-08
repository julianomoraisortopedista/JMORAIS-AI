from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MedicalDocument:
    title: str
    sections: list[dict[str, Any]] = field(default_factory=list)
    references: list[str] = field(default_factory=list)
    summary: str = ""


class MedicalDocumentGenerator:
    @staticmethod
    def build_summary(title: str, clinical_context: str, recommendations: list[str]) -> str:
        bullets = "\n".join(f"- {item}" for item in recommendations or ["No specific recommendation provided."])
        return (
            f"{title}\n\n"
            f"Clinical context: {clinical_context}\n\n"
            f"Key recommendations:\n{bullets}"
        )

    @staticmethod
    def build_evidence_pack(title: str, summary: str, evidence: list[dict[str, Any]]) -> MedicalDocument:
        sections = [
            {"heading": "Overview", "content": summary},
            {"heading": "Evidence", "content": "\n".join(
                f"- {item.get('claim_text') or item.get('title') or 'Evidence item'}"
                for item in evidence or []
            ) or "No evidence items provided."},
        ]
        references = []
        for item in evidence or []:
            if item.get("pmid"):
                references.append(f"PMID: {item['pmid']}")
            elif item.get("doi"):
                references.append(f"DOI: {item['doi']}")
        return MedicalDocument(title=title, sections=sections, references=references, summary=summary)

    @staticmethod
    def build_clinical_report(title: str, patient_context: str, decision: dict[str, Any]) -> MedicalDocument:
        summary = (
            f"This report summarizes the clinical decision for: {patient_context}. "
            f"Recommendation: {decision.get('recommendation') or 'No recommendation available.'}"
        )
        sections = [
            {"heading": "Clinical context", "content": patient_context},
            {"heading": "Recommendation", "content": decision.get("recommendation") or "No recommendation available."},
            {"heading": "Risk and caution", "content": "\n".join(decision.get("caution") or ["No specific cautions recorded."])},
            {"heading": "Evidence strength", "content": str(decision.get("evidence_strength") or "limited")},
        ]
        references = []
        for source in decision.get("source_ids") or []:
            references.append(str(source))
        return MedicalDocument(title=title, sections=sections, references=references, summary=summary)
