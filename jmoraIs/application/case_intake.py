"""Case intake: de-identified clinical documents -> AI-extracted, quote-grounded facts.

Only de-identified text reaches the Canonical LLM Gateway (human review mandatory).
Every extracted fact must carry a verbatim quote from the named source document or
history; facts without a matching quote are discarded as UNGROUNDED. ICD-10 codes are
returned only as suggestions for the physician to confirm. Images are never sent: photos
and scanned PDFs are read locally (`local_ocr`) and only their de-identified text continues.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import io
import json
import re
from typing import Callable
from uuid import uuid4

from jmoraIs.application import local_ocr
from jmoraIs.application.deidentification import DeidentifiedText, PatientIdentifiers, deidentify
from jmoraIs.llm_gateway.domain import (
    CanonicalStructuredDTO, LLMModel, LLMOutputClassification, LLMRequest, PromptTemplate, ReviewPolicy, StructuredField,
)

POLICY = "MIP-10.1"
SCHEMA_ID = "case-intake-input"
PROMPT_ID = "case-intake-extraction-v1"
MAX_OUTPUT_TOKENS = 12000
MAX_DOCUMENT_CHARS = 40000
TEXT_TYPES = (".pdf", ".txt", ".docx")
IMAGE_TYPES = (".jpg", ".jpeg", ".png")


class CaseIntakeRejected(ValueError):
    pass


class FactCategory(str, Enum):
    QUEIXA = "QUEIXA"
    EVOLUCAO = "EVOLUCAO"
    TRATAMENTO_CONSERVADOR = "TRATAMENTO_CONSERVADOR"
    EXAME_FISICO = "EXAME_FISICO"
    ACHADO_IMAGEM = "ACHADO_IMAGEM"
    ESCALA_FUNCIONAL = "ESCALA_FUNCIONAL"
    COMORBIDADE = "COMORBIDADE"
    INDICACAO = "INDICACAO"


CATEGORY_PT = {FactCategory.QUEIXA: "Queixa principal", FactCategory.EVOLUCAO: "Tempo de evolução",
               FactCategory.TRATAMENTO_CONSERVADOR: "Tratamento conservador", FactCategory.EXAME_FISICO: "Exame físico",
               FactCategory.ACHADO_IMAGEM: "Achado de imagem", FactCategory.ESCALA_FUNCIONAL: "Escala de dor/função",
               FactCategory.COMORBIDADE: "Comorbidade", FactCategory.INDICACAO: "Indicação cirúrgica"}

OUTPUT_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "facts": {"type": "array", "items": {"type": "object", "properties": {
            "category": {"type": "string", "enum": [c.value for c in FactCategory]},
            "statement": {"type": "string"}, "quote": {"type": "string"}, "source": {"type": "string"}},
            "required": ["category", "statement", "quote", "source"], "additionalProperties": False}},
        "icd10_suggestions": {"type": "array", "items": {"type": "object", "properties": {
            "code": {"type": "string"}, "description": {"type": "string"}},
            "required": ["code", "description"], "additionalProperties": False}},
    },
    "required": ["facts", "icd10_suggestions"],
    "additionalProperties": False,
}
INSTRUCTIONS = (
    "Você auxilia um médico ortopedista a montar um pedido de cirurgia. Os documentos já estão sem identificação "
    "do paciente. Extraia somente fatos clínicos presentes nos textos: queixa, tempo de evolução, tratamentos "
    "conservadores realizados (tipo e duração), exame físico, achados de imagem, escalas de dor/função, "
    "comorbidades e indicação. Para cada fato, escreva uma frase curta em português (statement), copie um trecho "
    "LITERAL do texto de origem que comprova o fato (quote) e informe o rótulo exato da origem (source). Não "
    "invente nem deduza dados ausentes. Sugira códigos CID-10 compatíveis apenas como sugestão para o médico "
    "confirmar. Responda somente com o JSON solicitado. Isto é um rascunho para revisão médica."
)


@dataclass(frozen=True)
class CaseDocument:
    label: str
    text: str
    removed: dict


@dataclass(frozen=True)
class ClinicalFact:
    fact_id: str
    category: FactCategory
    statement: str
    quote: str
    source: str


@dataclass(frozen=True)
class CaseExtraction:
    facts: tuple[ClinicalFact, ...]
    discarded: int
    icd10_suggestions: tuple[dict, ...]
    model_id: str
    status: str


def docx_text(content: bytes) -> str:
    """Paragraph text of a Word .docx (stdlib zip + XML; no macros or external parts)."""
    import zipfile
    from xml.etree.ElementTree import fromstring
    w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    try:
        book = zipfile.ZipFile(io.BytesIO(content))
        info = book.getinfo("word/document.xml")
        if info.file_size > 20_000_000:
            raise CaseIntakeRejected("Documento Word grande demais.")
        root = fromstring(book.read(info))
    except CaseIntakeRejected:
        raise
    except Exception as exc:
        raise CaseIntakeRejected("Não foi possível ler o documento Word.") from exc
    paragraphs = ["".join(t.text or "" for t in p.iter(w + "t")) for p in root.iter(w + "p")]
    text = "\n".join(p for p in paragraphs if p.strip())
    if len(text.strip()) < 40:
        raise CaseIntakeRejected("Documento Word sem texto.")
    return text


def extract_text(filename: str, content: bytes) -> str:
    name = (filename or "").lower()
    if name.endswith(".txt"):
        return content.decode("utf-8", errors="replace")
    if name.endswith(".docx"):
        return docx_text(content)
    if name.endswith(IMAGE_TYPES):
        return _ocr(local_ocr.ocr_image, content, "Foto")
    if not name.endswith(".pdf"):
        raise CaseIntakeRejected("Apenas PDF, Word (.docx), texto ou foto (JPG/PNG).")
    if not content.startswith(b"%PDF"):
        raise CaseIntakeRejected("Arquivo PDF inválido.")
    try:
        from pypdf import PdfReader  # optional dependency for case intake
        reader = PdfReader(io.BytesIO(content))
        if reader.is_encrypted:
            raise CaseIntakeRejected("PDF protegido por senha.")
        text = "\n".join((page.extract_text() or "") for page in reader.pages[:40])
    except CaseIntakeRejected:
        raise
    except Exception as exc:
        raise CaseIntakeRejected("Não foi possível ler o PDF.") from exc
    if len(text.strip()) < 40:
        return _ocr(local_ocr.ocr_pdf, content, "PDF escaneado")
    return text


def _ocr(read: Callable[[bytes], str], content: bytes, kind: str) -> str:
    """Local OCR (no AI); failures explain how to proceed without it."""
    try:
        text = read(content)
    except local_ocr.OCRUnavailable as exc:
        raise CaseIntakeRejected(f"{kind}: {exc}. Digite o laudo na história ou envie o PDF original com texto.") from exc
    if len(text.strip()) < local_ocr.MIN_TEXT_CHARS:
        raise CaseIntakeRejected(f"{kind} sem texto legível. Fotografe o laudo de frente, com boa luz, ou digite-o na história.")
    return text


def prepare_documents(files: list[tuple[str, bytes]], history: str, identifiers: PatientIdentifiers
                      ) -> tuple[DeidentifiedText, tuple[CaseDocument, ...]]:
    if not any(v for v in (identifiers.name, identifiers.cpf, identifiers.card_number)):
        raise CaseIntakeRejected("Informe ao menos o nome do paciente para que ele seja removido dos textos.")
    deid_history = deidentify(history or "", identifiers)
    documents = []
    for index, (filename, content) in enumerate(files, 1):
        text = extract_text(filename, content)[:MAX_DOCUMENT_CHARS]
        cleaned = deidentify(text, identifiers)
        documents.append(CaseDocument(f"Documento {index}", cleaned.text, cleaned.removed))
    return deid_history, tuple(documents)


def _normalize(text: str) -> str:
    return " ".join(text.split()).casefold()


def case_intake_prompt() -> PromptTemplate:
    return PromptTemplate(PROMPT_ID, "Case intake fact extraction", "Extract grounded clinical facts for physician review",
                          INSTRUCTIONS, ("CanonicalStructuredDTO",), "case-intake-output-v1", POLICY)


class CaseExtractionService:
    def __init__(self, gateway, *, prompt_version_id: str, model: LLMModel, clock: Callable[[], datetime]):
        self._gateway, self._prompt, self._model, self._clock = gateway, prompt_version_id, model, clock

    def extract(self, history: DeidentifiedText, documents: tuple[CaseDocument, ...]) -> CaseExtraction:
        sources = {"História": history.text, **{d.label: d.text for d in documents}}
        sources = {k: v for k, v in sources.items() if v.strip()}
        if not sources:
            raise CaseIntakeRejected("Envie a história ou ao menos um laudo.")
        dto = CanonicalStructuredDTO(SCHEMA_ID, "1", tuple(StructuredField(label, text, "deidentified:" + label)
                                                           for label, text in sources.items()),
                                     POLICY, tuple("deidentified:" + label for label in sources))
        response = self._gateway.invoke(LLMRequest(
            "case-" + uuid4().hex, self._prompt, self._model, dto,
            ReviewPolicy("physician-case-review", POLICY, True, False), 0.0, None, MAX_OUTPUT_TOKENS, POLICY, self._clock()))
        if response.classification is LLMOutputClassification.BLOCKED:
            return CaseExtraction((), 0, (), self._model.model_id, "BLOCKED")
        try:
            match = re.search(r"\{.*\}", response.output_text, re.DOTALL)
            data = json.loads(match.group(0) if match else response.output_text)
            raw_facts, raw_codes = list(data.get("facts") or []), list(data.get("icd10_suggestions") or [])
        except (ValueError, AttributeError, TypeError):
            return CaseExtraction((), 0, (), self._model.model_id, "UNGROUNDED")
        facts, discarded = [], 0
        normalized = {label: _normalize(text) for label, text in sources.items()}
        for item in raw_facts:
            try:
                category = FactCategory(str(item["category"]).upper())
                quote = " ".join(str(item["quote"]).split())
                source = str(item["source"]).strip()
                statement = " ".join(str(item["statement"]).split())[:400]
            except (KeyError, ValueError, TypeError):
                discarded += 1
                continue
            grounded = len(quote) >= 8 and "REMOVIDO]" not in quote and (
                _normalize(quote) in normalized.get(source, "") or
                any(_normalize(quote) in text for text in normalized.values()))
            if not grounded or not statement:
                discarded += 1
                continue
            if _normalize(quote) not in normalized.get(source, ""):
                source = next(label for label, text in normalized.items() if _normalize(quote) in text)
            facts.append(ClinicalFact("fact-" + uuid4().hex[:12], category, statement, quote, source))
        codes = tuple({"code": str(c.get("code", ""))[:10], "description": str(c.get("description", ""))[:160]}
                      for c in raw_codes if isinstance(c, dict) and re.fullmatch(r"[A-Z]\d{2}(\.\d{1,2})?", str(c.get("code", ""))))
        return CaseExtraction(tuple(facts), discarded, codes[:8], self._model.model_id, "PENDING_PHYSICIAN_REVIEW")
