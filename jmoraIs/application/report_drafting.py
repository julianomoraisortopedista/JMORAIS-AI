"""Professional medical report drafted by AI strictly from physician-confirmed facts.

Input: confirmed, de-identified clinical facts (each with its verbatim source quote) and
the procedure/OPME context stated by the physician, plus the articles of the surgery's
scientific library already re-verified for this request (E1, E2... = reference numbers,
each with its verbatim abstract quote). The model writes Portuguese prose
per section, citing fact ids for every sentence. A sentence is kept only if it cites
existing ids and every number it contains appears in the cited facts or context; others
are dropped and counted; a sentence in the scientific section must cite at least one
article, and cited articles become the reference marker "[n]". Missing information is returned as gaps, never filled in. The
result is a draft that the physician edits and signs.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import re
from typing import Callable
from uuid import uuid4

from jmoraIs.llm_gateway.domain import (
    CanonicalStructuredDTO, LLMModel, LLMOutputClassification, LLMRequest, PromptTemplate, ReviewPolicy, StructuredField,
)

POLICY = "MIP-10.1"
PROMPT_ID = "medical-report-draft-v1"
SECTIONS = (
    ("historia", "História clínica"),
    ("tratamentos", "Tratamento conservador realizado"),
    ("exame_fisico", "Exame físico"),
    ("imagem", "Exames de imagem"),
    ("indicacao", "Indicação cirúrgica"),
    ("evidencias", "Fundamentação científica"),
    ("opme", "Justificativa do OPME"),
    ("solicitacao", "Solicitação"),
)
STYLE_ID = "MODELO"
STYLE_INSTRUCTIONS = (
    " Quando houver o campo MODELO (modelo de relatório do próprio médico, sem identificação), siga a ordem das "
    "seções, os títulos (campo 'title'), o tom e as expressões típicas dele. O MODELO é só formato: nunca use "
    "dados clínicos, números, lados ou achados do MODELO, e nunca cite MODELO como fonte."
)
CONTEXT_ID = "CTX"
EVIDENCE_SECTION = "evidencias"
DIRECTION_PT = {"SUPPORTING": "a favor", "OPPOSING": "contra", "NEUTRAL": "neutro", "INCONCLUSIVE": "inconclusivo"}
EVIDENCE_INSTRUCTIONS = (
    " Os campos E1, E2... são artigos científicos verificados e aprovados pelo médico, com o trecho literal do resumo "
    "e a direção (a favor, contra, neutro). Na seção 'evidencias', escreva a fundamentação científica ligando o caso "
    "(fatos F) aos artigos (E): cada frase deve citar ao menos um E e afirmar só o que o trecho do artigo diz, sem "
    "exagerar o nível de evidência. Prefira diretrizes, meta-análises e ensaios randomizados. Se houver artigo contra "
    "ou neutro, mencione-o com honestidade e explique, somente com fatos F, por que o caso se enquadra na indicação. "
    "Na 'indicacao' você também pode citar E. Sem campos E, deixe 'evidencias' vazia."
)
INSTRUCTIONS = (
    "Você é um ortopedista sênior redigindo o relatório médico de um pedido de cirurgia ao convênio. Escreva em "
    "português formal, técnico e objetivo, em terceira pessoa ('Paciente apresenta...'). Use SOMENTE os fatos "
    "fornecidos (F1, F2...) e o contexto do procedimento (CTX). Cada frase deve citar os ids que a sustentam. Não "
    "invente dados, números, graus, escalas, datas, lateralidade ou achados que não estejam nos fatos. Se uma "
    "seção não tiver fatos suficientes, deixe-a vazia e descreva a lacuna em 'gaps' (ex.: 'Exame físico não "
    "documentado: descrever amplitude de movimento e estabilidade'). Na justificativa do OPME, relacione cada "
    "material à necessidade clínica documentada. Em 'solicitacao', peça a autorização do procedimento e do OPME "
    "do contexto (CTX). Em 'title' use o título padrão da seção, salvo quando houver MODELO. Responda somente com o JSON solicitado."
) + STYLE_INSTRUCTIONS + EVIDENCE_INSTRUCTIONS
OUTPUT_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "sections": {"type": "array", "items": {"type": "object", "properties": {
            "section": {"type": "string", "enum": [k for k, _ in SECTIONS]},
            "title": {"type": "string"},
            "sentences": {"type": "array", "items": {"type": "object", "properties": {
                "text": {"type": "string"}, "fact_ids": {"type": "array", "items": {"type": "string"}}},
                "required": ["text", "fact_ids"], "additionalProperties": False}}},
            "required": ["section", "title", "sentences"], "additionalProperties": False}},
        "gaps": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["sections", "gaps"],
    "additionalProperties": False,
}


class ReportDraftRejected(ValueError):
    pass


@dataclass(frozen=True)
class DraftSentence:
    text: str
    fact_ids: tuple[str, ...]


@dataclass(frozen=True)
class ReportDraft:
    sections: tuple[tuple[str, str, tuple[DraftSentence, ...]], ...]   # (key, title, sentences)
    gaps: tuple[str, ...]
    dropped: int
    model_id: str

    def as_text(self) -> str:
        parts = []
        for _, title, sentences in self.sections:
            if sentences:
                parts.append(f"{title}: " + " ".join(s.text for s in sentences))
        return "\n\n".join(parts)


def report_prompt() -> PromptTemplate:
    return PromptTemplate(PROMPT_ID, "Medical report draft", "Draft report sections from confirmed facts for physician review",
                          INSTRUCTIONS, ("CanonicalStructuredDTO",), "medical-report-output-v1", POLICY)


MAX_STYLE_CHARS = 14000
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


def _numbers(text: str) -> set[str]:
    return {n.replace(",", ".") for n in _NUMBER.findall(text or "")}


class ReportDraftingService:
    def __init__(self, gateway, *, prompt_version_id: str, model: LLMModel, clock: Callable[[], datetime]):
        self._gateway, self._prompt, self._model, self._clock = gateway, prompt_version_id, model, clock

    def draft(self, facts: list[dict], context: str, style: str = "", evidence: tuple = ()) -> ReportDraft:
        """`evidence`: re-verified library references as dicts with number, quote, direction and study."""
        if not facts:
            raise ReportDraftRejected("Confirme os fatos clínicos antes de redigir o relatório.")
        ids = {f"F{n}": fact for n, fact in enumerate(facts, 1)}
        support = {fid: f"{f['statement']} {f['quote']}" for fid, f in ids.items()}
        support[CONTEXT_ID] = context or ""
        fields = [StructuredField(fid, f"[{f['category_label']}] {f['statement']} (fonte: “{f['quote']}”)", "confirmed-fact")
                  for fid, f in ids.items()]
        fields.append(StructuredField(CONTEXT_ID, context or "(sem contexto)", "physician-request"))
        articles = {f"E{int(e['number'])}": e for e in evidence if str(e.get("quote") or "").strip()}
        for eid, e in articles.items():
            support[eid] = e["quote"]
            kind = "; ".join(x for x in (e.get("study") or "Artigo", DIRECTION_PT.get(e.get("direction"), "")) if x)
            fields.append(StructuredField(eid, f"[{kind}] “{e['quote']}”", "verified-evidence"))
        if style.strip():
            fields.append(StructuredField(STYLE_ID, style.strip()[:MAX_STYLE_CHARS], "physician-format-example"))
        dto = CanonicalStructuredDTO("medical-report-input", "1", tuple(fields), POLICY, ("confirmed-facts",))
        response = self._gateway.invoke(LLMRequest(
            "report-" + uuid4().hex, self._prompt, self._model, dto, ReviewPolicy("physician-report-review", POLICY, True, False),
            0.0, None, 8000, POLICY, self._clock()))
        if response.classification is LLMOutputClassification.BLOCKED:
            raise ReportDraftRejected("O modelo recusou a redação.")
        try:
            match = re.search(r"\{.*\}", response.output_text, re.DOTALL)
            data = json.loads(match.group(0) if match else response.output_text)
        except (ValueError, AttributeError):
            raise ReportDraftRejected("Resposta do modelo fora do formato. Tente de novo.") from None
        by_key: dict[str, list[DraftSentence]] = {k: [] for k, _ in SECTIONS}
        titles = dict(SECTIONS)
        order: list[str] = []
        dropped = 0
        for section in data.get("sections") or []:
            key = section.get("section")
            if key not in by_key:
                continue
            title = " ".join(str(section.get("title") or "").split())[:80]
            if style.strip() and title:
                titles[key] = title
            if key not in order:
                order.append(key)
            for sentence in section.get("sentences") or []:
                text = " ".join(str(sentence.get("text", "")).split())[:600]
                cited = tuple(dict.fromkeys(str(i).strip().upper() for i in sentence.get("fact_ids") or []))
                valid = text and cited and all(i in support for i in cited)
                allowed = set().union(*(_numbers(support[i]) for i in cited)) if valid else set()
                cites = [i for i in cited if i in articles]
                if not valid or not _numbers(text) <= allowed or (key == EVIDENCE_SECTION and not cites):
                    dropped += 1
                    continue
                if cites:  # reference markers follow the request's numbering, added after the number check
                    text = text.rstrip() + " [" + ",".join(i[1:] for i in cites) + "]"
                by_key[key].append(DraftSentence(text, cited))
        gaps = tuple(" ".join(str(g).split())[:300] for g in data.get("gaps") or [] if str(g).strip())[:12]
        # Default order, or the order the physician's model produced; sections not emitted follow.
        order = (order if style.strip() else []) + [k for k, _ in SECTIONS if k not in order or not style.strip()]
        return ReportDraft(tuple((k, titles[k], tuple(by_key[k])) for k in order), gaps, dropped, self._model.model_id)
