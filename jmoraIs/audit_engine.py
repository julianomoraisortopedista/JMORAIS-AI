from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AuditClaim:
    claim_id: str
    raw_claim: str
    category: str = "general"
    evidence_needed: list[str] = field(default_factory=list)
    source_refs: list[str] = field(default_factory=list)
    risk: str = "medium"


@dataclass
class AuditEvidenceMatrix:
    claim_id: str
    claim_text: str
    supporting: list[str] = field(default_factory=list)
    opposing: list[str] = field(default_factory=list)
    neutral: list[str] = field(default_factory=list)
    assessed_status: str = "needs_review"
    notes: str = ""


@dataclass
class AuditDefenseResponse:
    claim_id: str
    response: str
    confidence: float
    evidence_strength: str
    cited_sources: list[str]


class AuditDefenseEngine:
    @staticmethod
    def parse_claims(document_text: str) -> list[AuditClaim]:
        if not document_text or not document_text.strip():
            return []

        sentences = [s.strip() for s in document_text.replace("\n", " ").split(".") if s.strip()]
        claims: list[AuditClaim] = []
        for index, sentence in enumerate(sentences[:20], start=1):
            claim = sentence.strip()
            category = "medical" if any(token in claim.lower() for token in ["treatment", "procedure", "device", "diagnosis", "rehabilitation"]) else "general"
            claims.append(
                AuditClaim(
                    claim_id=f"claim-{index}",
                    raw_claim=claim,
                    category=category,
                    evidence_needed=["source verification", "clinical applicability"],
                    source_refs=[],
                    risk="medium" if category == "general" else "high",
                )
            )
        return claims

    @staticmethod
    def build_evidence_matrix(claims: list[AuditClaim], evidence: list[dict[str, Any]]) -> list[AuditEvidenceMatrix]:
        matrices: list[AuditEvidenceMatrix] = []
        for claim in claims:
            supporting: list[str] = []
            opposing: list[str] = []
            neutral: list[str] = []
            for item in evidence:
                direction = str(item.get("support_direction") or "supporting").lower()
                text = str(item.get("claim_text") or item.get("title") or "Evidence item")
                if direction == "supporting":
                    supporting.append(text)
                elif direction == "opposing":
                    opposing.append(text)
                else:
                    neutral.append(text)
            status = "supported" if supporting else "needs_review"
            notes = "Evidence matrix generated from available record-level support/opposition assessment." if supporting or opposing or neutral else "No evidence has been attached to this claim yet."
            matrices.append(
                AuditEvidenceMatrix(
                    claim_id=claim.claim_id,
                    claim_text=claim.raw_claim,
                    supporting=supporting,
                    opposing=opposing,
                    neutral=neutral,
                    assessed_status=status,
                    notes=notes,
                )
            )
        return matrices

    @staticmethod
    def generate_defense_response(claim: AuditClaim, matrix: AuditEvidenceMatrix, evidence: list[dict[str, Any]]) -> AuditDefenseResponse:
        sources = []
        for item in evidence:
            if item.get("pmid"):
                sources.append(str(item["pmid"]))
            elif item.get("doi"):
                sources.append(str(item["doi"]))

        if matrix.supporting:
            response = (
                f"The audit claim '{claim.raw_claim}' is supported by the reviewed evidence base and should be framed as a clinically contextualized interpretation."
            )
            confidence = 0.8
            strength = "moderate"
        elif matrix.opposing:
            response = (
                f"The audit claim '{claim.raw_claim}' is not sufficiently supported. The available evidence indicates a need to clarify context, limitations, and applicability."
            )
            confidence = 0.55
            strength = "limited"
        else:
            response = (
                f"The audit claim '{claim.raw_claim}' requires additional evidence before it can be considered complete or defensible."
            )
            confidence = 0.3
            strength = "insufficient"

        return AuditDefenseResponse(
            claim_id=claim.claim_id,
            response=response,
            confidence=confidence,
            evidence_strength=strength,
            cited_sources=list(dict.fromkeys(sources)),
        )
