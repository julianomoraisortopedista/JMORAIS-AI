"""Scientific justification draft built only from physician-confirmed, re-verified evidence.

Input: one claim and the physician decisions produced by the classification step
(`scripts/classify_evidence.py --out`). Every decision is re-checked before use:
the PubMed abstract is fetched again and must have the same SHA-256, the quote
must still be verbatim, the publication must still reach VERIFIED through the
authoritative PubMed/Crossref pipeline, and the Vancouver text comes only from
the strict formatter. No model-generated prose enters the draft. Supporting,
opposing, neutral and inconclusive evidence are all listed; excluded items are
reported with the reason. The result is a DRAFT for physician review and contains
no patient data.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Iterable, Optional

from jmoraIs.application.scientific_verification import (
    ScientificVerificationInput, TrustedEvidenceIssuanceError,
)
from jmoraIs.application.support_classification import (
    CLASSIFIER_VERSION, PhysicianDecisionType, PhysicianSupportDecision, ProposalStatus,
    SupportClassificationProposal, _is_verbatim, register_confirmed_support,
)
from jmoraIs.connect.pubmed import AbstractUnavailable
from jmoraIs.evidence_ledger import AppendOnlyEvidenceLedger
from jmoraIs.scientific_domain import SupportDirection
from jmoraIs.vancouver import StrictVancouverFormatter, VancouverBlockedError

SECTION_TITLES = {
    SupportDirection.SUPPORTING: "Evidências a favor",
    SupportDirection.OPPOSING: "Evidências contrárias",
    SupportDirection.NEUTRAL: "Evidências neutras",
    SupportDirection.INCONCLUSIVE: "Evidências inconclusivas",
}
DIRECTION_PT = {d: t.split(" ", 1)[1] for d, t in SECTION_TITLES.items()}


class JustificationRejected(ValueError):
    pass


# PubMed publication types that count as high-level evidence (STF, ADI 7265: randomized
# trials, systematic reviews, meta-analyses; guidelines kept separate as ATS-like sources).
HIGH_LEVEL_TYPES = ("Randomized Controlled Trial", "Systematic Review", "Meta-Analysis")
GUIDELINE_TYPES = ("Practice Guideline", "Guideline")
STUDY_TYPE_PT = {"Randomized Controlled Trial": "ensaio clínico randomizado", "Systematic Review": "revisão sistemática",
                 "Meta-Analysis": "meta-análise", "Practice Guideline": "diretriz", "Guideline": "diretriz"}


@dataclass(frozen=True)
class JustifiedReference:
    number: int
    pmid: str
    direction: SupportDirection
    quote: str
    vancouver: str
    package_id: str
    reviewer: str
    decision: str
    model: str
    study_types: tuple[str, ...] = ()

    @property
    def high_level(self) -> bool:
        return any(t in HIGH_LEVEL_TYPES for t in self.study_types)

    @property
    def study_label(self) -> str:
        labels = [STUDY_TYPE_PT[t] for t in self.study_types if t in STUDY_TYPE_PT]
        return ", ".join(dict.fromkeys(labels))


@dataclass(frozen=True)
class ExcludedEvidence:
    pmid: str
    reason: str


@dataclass(frozen=True)
class JustificationDraft:
    claim: str
    references: tuple[JustifiedReference, ...]
    excluded: tuple[ExcludedEvidence, ...]
    created_at: datetime

    def by_direction(self, direction: SupportDirection) -> tuple[JustifiedReference, ...]:
        return tuple(r for r in self.references if r.direction is direction)


def _decision_from_record(record: dict, abstract_hash: str, created_at: datetime) -> PhysicianSupportDecision:
    proposal = SupportClassificationProposal(
        "prop-" + record["pmid"], record["claim"], record["pmid"], abstract_hash, record["source"],
        ProposalStatus(record["ai_status"]),
        SupportDirection(record["ai_direction"]) if record.get("ai_direction") else None,
        record["quote"], record.get("ai_rationale") or "", "replay", record["model"],
        record["prompt_version"], created_at)
    return PhysicianSupportDecision(
        "dec-" + record["pmid"], proposal, PhysicianDecisionType(record["physician_decision"]),
        SupportDirection(record["final_direction"]), record["reviewer"], record.get("note") or "",
        datetime.fromisoformat(record["decided_at"]))


def build_justification(claim: str, records: Iterable[dict], *, pubmed, pipeline, packages,
                        clock: Callable[[], datetime]) -> JustificationDraft:
    claim = " ".join((claim or "").split())
    if len(claim) < 10:
        raise JustificationRejected("a specific claim is required")
    now = clock()
    ledger = AppendOnlyEvidenceLedger()
    ledger.create_claim(claim, claim_id="claim-1", created_at=now)
    formatter = StrictVancouverFormatter(packages, clock=clock)
    references: list[JustifiedReference] = []
    excluded: list[ExcludedEvidence] = []
    seen: set[str] = set()
    for record in records:
        pmid = str(record.get("pmid") or "")
        if pmid in seen:
            excluded.append(ExcludedEvidence(pmid, "decisão duplicada para o mesmo PMID"))
            continue
        seen.add(pmid)
        if " ".join(str(record.get("claim") or "").split()) != claim:
            excluded.append(ExcludedEvidence(pmid, "decisão tomada para outra afirmação"))
            continue
        if record.get("physician_decision") == PhysicianDecisionType.REJECT.value or not record.get("final_direction"):
            excluded.append(ExcludedEvidence(pmid, "rejeitado pelo médico"))
            continue
        try:
            abstract = pubmed.fetch_abstract(pmid)
        except AbstractUnavailable as exc:
            excluded.append(ExcludedEvidence(pmid, f"resumo indisponível no PubMed agora ({exc})"))
            continue
        if abstract.content_hash != record.get("abstract_sha256"):
            excluded.append(ExcludedEvidence(pmid, "o resumo mudou desde a revisão médica; classifique de novo"))
            continue
        if not record.get("quote") or not _is_verbatim(record["quote"], abstract):
            excluded.append(ExcludedEvidence(pmid, "o trecho não é literal do resumo"))
            continue
        try:
            decision = _decision_from_record(record, abstract.content_hash, abstract.retrieved_at)
            _, support, _ = register_confirmed_support(decision, ledger=ledger, claim_id="claim-1")
            trusted = pipeline.issue_trusted_publications(
                ScientificVerificationInput(pmid=pmid), ledger=ledger, claim_id="claim-1",
                support_ids=(support.support_id,), pipeline_version=CLASSIFIER_VERSION)
        except TrustedEvidenceIssuanceError:
            excluded.append(ExcludedEvidence(pmid, "metadados bibliográficos não VERIFICADOS (PubMed/Crossref divergem)"))
            continue
        except (KeyError, ValueError) as exc:
            excluded.append(ExcludedEvidence(pmid, f"registro de decisão inválido ({type(exc).__name__})"))
            continue
        publication = next((t for t in trusted if t.article.pmid == pmid), None)
        if publication is None:
            excluded.append(ExcludedEvidence(pmid, "registro verificado não corresponde ao PMID"))
            continue
        try:
            vancouver = formatter.render(package_id=publication.package.package_id, article=publication.article)
        except VancouverBlockedError as exc:
            excluded.append(ExcludedEvidence(pmid, f"Vancouver bloqueado ({exc})"))
            continue
        references.append(JustifiedReference(
            len(references) + 1, pmid, decision.final_direction, record["quote"], vancouver.rendered_text,
            publication.package.package_id, decision.reviewer_id, decision.decision.value, record["model"],
            tuple((publication.article.raw_metadata or {}).get("publication_types") or ())))
    ledger.verify_integrity("claim-1")
    return JustificationDraft(claim, tuple(references), tuple(excluded), now)


def render_markdown(draft: JustificationDraft) -> str:
    lines = ["# Fundamentação científica — RASCUNHO PARA REVISÃO MÉDICA", "",
             f"**Afirmação avaliada:** {draft.claim}", "",
             f"Gerado em {draft.created_at.strftime('%Y-%m-%d %H:%M UTC')}. Apenas artigos com metadados "
             "verificados no PubMed e no Crossref, classificados com confirmação médica. Os trechos são "
             "citações literais dos resumos publicados (em inglês).", ""]
    counts = ", ".join(f"{len(draft.by_direction(d))} {DIRECTION_PT[d]}" for d in SECTION_TITLES)
    lines += [f"**Resumo da evidência:** {counts}.", ""]
    for direction, title in SECTION_TITLES.items():
        items = draft.by_direction(direction)
        lines.append(f"## {title} ({len(items)})")
        lines.append("")
        if not items:
            lines.append("Nenhuma evidência confirmada nesta categoria.")
        for ref in items:
            kind = f" ({ref.study_label})" if ref.study_label else ""
            lines.append(f'- [{ref.number}] PMID {ref.pmid}{kind}: "{ref.quote}"')
        lines.append("")
    lines += ["## Referências (Vancouver)", ""]
    lines += [f"{ref.number}. {ref.vancouver}" for ref in draft.references] or ["Nenhuma referência verificada."]
    lines += ["", "## Rastreabilidade", ""]
    lines += [f"- [{r.number}] decisão {r.decision} por {r.reviewer}; sugestão inicial por {r.model}; "
              f"pacote de evidência {r.package_id}" for r in draft.references]
    if draft.excluded:
        lines += ["", "## Não incluídos", ""]
        lines += [f"- PMID {e.pmid}: {e.reason}" for e in draft.excluded]
    lines += ["", "---", "Documento técnico de apoio. Não substitui o julgamento clínico e exige revisão e "
              "assinatura do médico responsável antes de qualquer envio externo."]
    return "\n".join(lines) + "\n"
