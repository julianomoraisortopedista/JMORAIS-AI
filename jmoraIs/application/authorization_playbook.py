"""Authorization playbook: what each insurer denies, why, and what has worked.

A per-installation knowledge base kept by the physician (0600 JSON, atomic writes, outside
the repository). It holds no patient data: cases are recorded by insurer, date, region,
codes, quantities, materials, denial reasons and outcome only, and free text is refused when
identifiers are detected. Denial reasons carry prevention steps, response arguments, legal
source ids from the verified legal library and PubMed ids; whether those ids still verify is
checked where they are used (citation check, justification builder), not trusted here.
Insurer rules turn observed patterns into warnings for a request (codes + insurer name).
"""
from __future__ import annotations

from datetime import date
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import unicodedata
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from jmoraIs.application.deidentification import detect_identifiers

OUTCOMES = ("APROVADO", "APROVADO_PARCIAL", "NEGADO", "REVERTIDO", "MANTIDO", "PENDENTE")


class PlaybookRejected(ValueError):
    pass


def _fold(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", value or "") if not unicodedata.combining(c)).casefold()


def _clean(texts: list[str]) -> None:
    for text in texts:
        if text and detect_identifiers(text):
            raise PlaybookRejected("Há dados de paciente no texto. Registre o caso sem nome, CPF, carteirinha ou data de nascimento.")


class Reason(BaseModel):
    reason_id: str = Field(pattern=r"^[a-z0-9_]{3,40}$")
    label: str = Field(min_length=3, max_length=160)
    prevention: list[str] = Field(default_factory=list, max_length=12)
    response: list[str] = Field(default_factory=list, max_length=12)
    legal: list[str] = Field(default_factory=list, max_length=12)       # ids in the verified legal library
    evidence: list[str] = Field(default_factory=list, max_length=20)    # PubMed ids
    keywords: list[str] = Field(default_factory=list, max_length=20)    # phrases that reveal this reason in a denial

    @field_validator("evidence")
    @classmethod
    def _pmids(cls, value):
        if any(not re.fullmatch(r"[1-9]\d{0,8}", v) for v in value):
            raise ValueError("PMID inválido")
        return value


class Rule(BaseModel):
    codes: list[str] = Field(default_factory=list, max_length=10)       # any of these codes in the request triggers it
    message: str = Field(min_length=5, max_length=600)
    blocking: bool = False


class Reviewer(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    registry: str = Field("", max_length=40)
    role: str = Field("", max_length=60)                                 # auditor, desempatador, 2ª opinião
    note: str = Field("", max_length=400)


class Insurer(BaseModel):
    insurer_id: str = Field(pattern=r"^[a-z0-9_]{2,40}$")
    name: str = Field(min_length=2, max_length=80)
    aliases: list[str] = Field(default_factory=list, max_length=10)      # words matched in the insurer field
    route: str = Field("", max_length=200)                               # e.g. "auditoria Advice Health; OPME via Orizon"
    tactics: list[str] = Field(default_factory=list, max_length=20)
    responses: list[str] = Field(default_factory=list, max_length=20)
    reviewers: list[Reviewer] = Field(default_factory=list, max_length=40)
    rules: list[Rule] = Field(default_factory=list, max_length=20)


class Line(BaseModel):
    code: str = Field(min_length=3, max_length=40)                       # TUSS code or material description
    requested: int = Field(0, ge=0, le=99)
    authorized: Optional[int] = Field(None, ge=0, le=99)


class Case(BaseModel):
    case_id: str = ""
    insurer_id: str = Field(pattern=r"^[a-z0-9_]{2,40}$")
    on: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    stage: str = Field("", max_length=60)                                # pedido, consenso, junta, 2ª opinião
    region: str = Field("", max_length=80)
    lines: list[Line] = Field(default_factory=list, max_length=20)
    reasons: list[str] = Field(default_factory=list, max_length=10)
    outcome: str = Field("PENDENTE")
    notes: str = Field("", max_length=1500)

    @field_validator("outcome")
    @classmethod
    def _outcome(cls, value):
        if value not in OUTCOMES:
            raise ValueError("Resultado inválido")
        return value


class Playbook(BaseModel):
    version: int = 1
    reasons: list[Reason] = Field(default_factory=list)
    insurers: list[Insurer] = Field(default_factory=list)
    cases: list[Case] = Field(default_factory=list)


class PlaybookStore:
    def __init__(self, path: Path):
        self._path = Path(path)
        self._lock = threading.Lock()

    def load(self) -> Playbook:
        if not self._path.exists():
            return Playbook()
        return Playbook.model_validate(json.loads(self._path.read_text(encoding="utf-8")))

    def _write(self, book: Playbook) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=".playbook-")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(book.model_dump(), handle, ensure_ascii=False, indent=1)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self._path)

    def replace(self, book: Playbook) -> Playbook:
        """Whole-book write (seeding/import); every free text is checked for identifiers."""
        texts = [c.notes for c in book.cases] + [t for i in book.insurers for t in (*i.tactics, *i.responses)]
        _clean(texts)
        reasons = {r.reason_id for r in book.reasons}
        insurers = {i.insurer_id for i in book.insurers}
        for case in book.cases:
            if case.insurer_id not in insurers or any(r not in reasons for r in case.reasons):
                raise PlaybookRejected("Caso com convênio ou motivo desconhecido.")
        with self._lock:
            self._write(book)
        return book

    def add_case(self, case: Case) -> Case:
        _clean([case.notes, case.region, case.stage])
        with self._lock:
            book = self.load()
            if case.insurer_id not in {i.insurer_id for i in book.insurers}:
                raise PlaybookRejected("Convênio desconhecido.")
            if any(r not in {x.reason_id for x in book.reasons} for r in case.reasons):
                raise PlaybookRejected("Motivo de negativa desconhecido.")
            saved = case.model_copy(update={"case_id": "cas-" + uuid4().hex[:10]})
            book.cases.append(saved)
            self._write(book)
        return saved

    def set_outcome(self, case_id: str, outcome: str, notes: str = "") -> Case:
        if outcome not in OUTCOMES:
            raise PlaybookRejected("Resultado inválido.")
        _clean([notes])
        with self._lock:
            book = self.load()
            for n, case in enumerate(book.cases):
                if case.case_id == case_id:
                    book.cases[n] = case.model_copy(update={"outcome": outcome, "notes": (notes or case.notes)})
                    self._write(book)
                    return book.cases[n]
        raise PlaybookRejected("Caso não encontrado.")


def match_insurer(book: Playbook, name: str) -> Optional[Insurer]:
    folded = _fold(name)
    if not folded.strip():
        return None
    return next((i for i in book.insurers if any(_fold(a) in folded for a in [i.name, *i.aliases])), None)


def advice(book: Playbook, insurer_name: str, codes: list[str]) -> dict:
    """Warnings and track record for a request to this insurer with these codes."""
    insurer = match_insurer(book, insurer_name)
    if insurer is None:
        return {"insurer": None, "warnings": [], "record": {}, "top_reasons": []}
    codes = set(codes)
    warnings = [r.model_dump() for r in insurer.rules if not r.codes or codes & set(r.codes)]
    cases = [c for c in book.cases if c.insurer_id == insurer.insurer_id]
    record: dict[str, int] = {}
    for case in cases:
        record[case.outcome] = record.get(case.outcome, 0) + 1
    counts: dict[str, int] = {}
    for case in cases:
        for reason in case.reasons:
            counts[reason] = counts.get(reason, 0) + 1
    labels = {r.reason_id: r for r in book.reasons}
    top = [dict(reason_id=k, label=labels[k].label, count=v, prevention=labels[k].prevention)
           for k, v in sorted(counts.items(), key=lambda x: -x[1])[:5] if k in labels]
    return {"insurer": insurer.name, "route": insurer.route, "warnings": warnings, "record": record, "top_reasons": top}


def analyze(book: Playbook, text: str, codes: Optional[list[str]] = None) -> dict:
    """Which insurer wrote this denial and which known reasons it uses (deterministic, local)."""
    folded = _fold(text)
    insurer = match_insurer(book, text)
    reasons = [r for r in book.reasons if any(_fold(k) in folded for k in r.keywords)]
    found_codes = sorted(set(re.findall(r"(?<!\d)([34]\d{7})(?!\d)", text or "")) | set(codes or []))
    base = advice(book, insurer.name, found_codes) if insurer else {"insurer": None, "warnings": [], "record": {}, "top_reasons": []}
    return {**base, "codes": found_codes, "insurer_responses": insurer.responses if insurer else [],
            "reasons": [dict(reason_id=r.reason_id, label=r.label, response=r.response, prevention=r.prevention,
                             legal=r.legal, evidence=r.evidence) for r in reasons]}


def strategy_text(analysis: dict) -> str:
    """Argument lines for the contestation writer: guidance only, never a citable source."""
    lines = []
    if analysis.get("insurer"):
        lines.append(f"Convênio: {analysis['insurer']}. " + " ".join(analysis.get("insurer_responses") or []))
    for r in analysis.get("reasons") or []:
        lines.append(f"Motivo '{r['label']}': " + " ".join(r["response"]))
    return "\n".join(line for line in lines if line.strip())[:4000]


def today() -> str:
    return date.today().isoformat()
