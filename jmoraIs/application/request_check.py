"""Pre-submission check of a surgery request against the SBOT coding manual entry.

Deterministic and explainable: each finding says what was compared and where the rule
comes from. Findings are advice to the physician, never changes to the request.
Levels: BLOQUEIO (very likely denial), ATENCAO (review), OK (requirement met).
Sources: SBOT coding manual (codes, exclusive groups, OPME, exams, ICD-10, character) and
SBOT practical guide POP ("nunca pedir código que não possa defender"; "nunca
'emergenciar' procedimentos não compatíveis").
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from jmoraIs.reference.sbot import SbotEntry, fold

EXAM_TERMS = {  # manual wording -> words that show the exam in the documents
    "radiografia": ("radiografia", "raio-x", "raio x", "rx ", "rx:", "radiografias", "escanometria", "panoramica"),
    "ressonancia": ("ressonancia", "rnm", "rm ", "rm:", "rm do", "rm de"),
    "tomografia": ("tomografia", "tc ", "tc:", "angiotomografia"),
    "ultrassonografia": ("ultrassonografia", "ultrassom", "ultra-som", "usg", "ecografia"),
    "eletroneuromiografia": ("eletroneuromiografia", "enmg", "eletroneuro"),
    "densitometria": ("densitometria",),
    "cintilografia": ("cintilografia",),
}
GENERIC_OPME_WORDS = {"de", "da", "do", "com", "sem", "ou", "e", "em", "para", "tipo", "mm", "inclui"}


@dataclass(frozen=True)
class Finding:
    level: str      # BLOQUEIO / ATENCAO / OK
    topic: str
    message: str


def _words(text: str) -> set[str]:
    return {w for w in re.split(r"[^a-z0-9]+", fold(text)) if len(w) >= 3 and w not in GENERIC_OPME_WORDS}


def check_request(entry: SbotEntry, *, tuss_codes: list[str], icd10: list[str], opme: list[tuple[str, int]],
                  urgency: str, documents_text: str) -> list[Finding]:
    ref = f"SBOT {entry.entry_id}"
    findings: list[Finding] = []
    allowed = {c.digits: c for c in entry.codes}
    for code in tuss_codes:
        if code not in allowed:
            findings.append(Finding("ATENCAO", "Códigos",
                                    f"TUSS {code} não está entre os códigos do {ref} para este procedimento. "
                                    "Só peça código que possa defender com o relatório e os exames."))
    groups: dict[str, list[str]] = {}
    for code in tuss_codes:
        if code in allowed and allowed[code].exclusive_group:
            groups.setdefault(allowed[code].exclusive_group, []).append(code)
    for group, codes in groups.items():
        if len(codes) > 1:
            findings.append(Finding("BLOQUEIO", "Códigos",
                                    f"Códigos {', '.join(codes)} são excludentes entre si no {ref}: peça só um."))
    if tuss_codes and not any(f.topic == "Códigos" for f in findings):
        findings.append(Finding("OK", "Códigos", f"Códigos previstos no {ref}."))

    if entry.icd10:
        roots = {c[:3] for c in entry.icd10}
        if not icd10:
            findings.append(Finding("ATENCAO", "CID-10", f"Nenhum CID confirmado. O {ref} lista: {', '.join(entry.icd10)}."))
        elif not any(c[:3] in roots for c in icd10):
            findings.append(Finding("ATENCAO", "CID-10", f"CID {', '.join(icd10)} fora da lista do {ref} "
                                                          f"({', '.join(entry.icd10)}). Explique a indicação no relatório."))
        else:
            findings.append(Finding("OK", "CID-10", f"CID compatível com o {ref}."))

    if urgency and urgency not in entry.characters:
        level = "BLOQUEIO" if urgency in ("URGENCIA", "EMERGENCIA") else "ATENCAO"
        findings.append(Finding(level, "Caráter",
                                f"Pedido como {urgency.lower()}, mas o {ref} indica: {entry.character}. "
                                "Não marque urgência em procedimento eletivo (POP SBOT)."))

    text = fold(" " + documents_text + " ")
    needed = [key for key in EXAM_TERMS if key in fold(entry.exams)]
    found = [key for key in needed if any(term in text for term in EXAM_TERMS[key])]
    others = [key for key in needed if key not in found]
    if needed and not found:  # the manual lists the exams of the indication; at least one report is expected
        findings.append(Finding("ATENCAO", "Exames", f"Nenhum laudo dos exames citados no {ref} "
                                                      f"({', '.join(needed)}) foi encontrado nos documentos. Anexe ou justifique."))
    elif found:
        extra = f" O manual também cita {', '.join(others)}: anexe se foram feitos." if others else ""
        findings.append(Finding("OK", "Exames", f"Laudo de {', '.join(found)} presente nos documentos.{extra}"))

    reference = [(_words(o.description), o.quantity, o.description) for o in entry.opme]
    for description, quantity in opme:
        words = _words(description)
        match = max(reference, key=lambda r: len(words & r[0]), default=None)
        if match is None or not words & match[0]:
            findings.append(Finding("ATENCAO", "OPME", f"\"{description}\" não está no kit do {ref}. "
                                                        "Descreva no relatório em que tempo cirúrgico será usado."))
        elif quantity > match[1]:
            findings.append(Finding("ATENCAO", "OPME", f"\"{description}\": {quantity} unidade(s); o {ref} prevê "
                                                        f"{match[1]} ({match[2]}). Justifique a quantidade."))
    if opme and not any(f.topic == "OPME" for f in findings):
        findings.append(Finding("OK", "OPME", f"OPME dentro do kit e das quantidades do {ref}."))
    return findings
