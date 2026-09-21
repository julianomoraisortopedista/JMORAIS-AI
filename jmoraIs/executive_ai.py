from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ExecutiveBrief:
    title: str
    executive_summary: str
    key_findings: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    recommendations: tuple[str, ...] = ()
    evidence_sources: tuple[str, ...] = ()


class ExecutiveAI:
    @staticmethod
    def synthesize(
        title: str,
        clinical_summary: str,
        evidence: list[dict[str, Any]] | None = None,
        audit_findings: list[dict[str, Any]] | None = None,
        document_summary: str | None = None,
    ) -> ExecutiveBrief:
        evidence = evidence or []
        audit_findings = audit_findings or []

        findings = [
            clinical_summary,
            *(f"Audit finding: {item.get('claim_text') or item.get('raw_claim') or item.get('title') or 'Summary'}" for item in audit_findings),
        ]
        if not findings:
            findings = ["No further findings were supplied."]

        source_ids = []
        for item in evidence:
            if item.get("pmid"):
                source_ids.append(f"PMID: {item['pmid']}")
            elif item.get("doi"):
                source_ids.append(f"DOI: {item['doi']}")

        risks = [
            "Potential uncertainty in source applicability.",
            "Need for specialist review when evidence is mixed or limited.",
        ]
        recommendations = [
            "Prioritize evidence-backed clinical decisions.",
            "Review the audit posture where evidence is not definitive.",
            "Document assumptions, limitations, and provenance for final reports.",
        ]

        if document_summary:
            findings.append(document_summary)

        return ExecutiveBrief(
            title=title,
            executive_summary=(
                f"This executive brief consolidates the clinical, evidentiary, and audit context for {title}. "
                "The current recommendation is to keep decisions evidence-first, minimize unsupported conclusions, and document uncertainty explicitly."
            ),
            key_findings=tuple(findings[:5]),
            risks=tuple(risks),
            recommendations=tuple(recommendations),
            evidence_sources=tuple(dict.fromkeys(source_ids)),
        )
