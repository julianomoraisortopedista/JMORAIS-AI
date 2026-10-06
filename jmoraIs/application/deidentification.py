"""Remove patient identifiers from clinical text before any external processing (LGPD).

Two layers: (1) the identifiers the physician typed for this case (name parts, CPF,
RG, insurance card number, birth date, phone, e-mail, address) are removed wherever
they appear, accent- and case-insensitively; (2) generic patterns (CPF, CNS, RG,
phone, e-mail, CEP, labelled name/card/address/birth lines) are removed even when
not supplied. A final check refuses the text if any supplied identifier survives.
Clinical content (exam dates, ages, findings) is preserved.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
import unicodedata
from typing import Optional


class DeidentificationRejected(ValueError):
    pass


@dataclass(frozen=True)
class PatientIdentifiers:
    name: str = ""
    cpf: str = ""
    rg: str = ""
    card_number: str = ""
    birth_date: str = ""
    phone: str = ""
    email: str = ""
    address: str = ""
    extra: tuple[str, ...] = ()


@dataclass(frozen=True)
class DeidentifiedText:
    text: str
    removed: dict = field(default_factory=dict)  # category -> count (no values kept)


def _fold(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c)).casefold()


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


_LABELLED = [  # label followed by the identifying value on the same line
    ("MAE", r"(?im)(?<!\w)(?P<label>(?:nome\s+da\s+m[aã]e|m[aã]e|respons[aá]vel)\s*[:\-])[^\n]*?(?=\s{2,}|$)"),
    ("NOME", r"(?im)(?<!\w)(?P<label>(?:nome(?:\s+do\s+paciente)?|paciente|benefici[aá]rio|titular)\s*[:\-])[^\n]*?(?=\s{2,}|\s+(?:idade|sexo|data|dn|conv[eê]nio)\b|$)"),
    ("CARTEIRINHA", r"(?im)(?P<label>(?:carteir(?:a|inha)|matr[ií]cula|c[oó]d(?:igo)?\.?\s+(?:do\s+)?benefici[aá]rio|cart[aã]o(?:\s+(?:do\s+)?conv[eê]nio)?)\s*(?:n[ºo°.]*)?\s*[:\-]?)\s*[A-Z]{0,4}\d(?:[\d.\-/]| (?=\d))*"),
    ("NASCIMENTO", r"(?im)(?P<label>(?:data\s+de\s+)?nasc(?:imento)?\.?\s*[:\-]?)\s*\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}"),
    ("ENDERECO", r"(?im)(?<!\w)(?P<label>(?:endere[cç]o|resid[eê]ncia|logradouro)\s*[:\-])[^\n]*?(?=\s{2,}|\s+cep\b|$)"),
]
_PATTERNS = [
    ("CPF", r"\b\d{3}\.?\d{3}\.?\d{3}\s?-?\s?\d{2}\b"),
    ("CNS", r"\b[1-9]\d{2}\s?\d{4}\s?\d{4}\s?\d{4}\b"),
    ("EMAIL", r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    ("TELEFONE", r"(?<!\d)(?:\+?55\s?)?\(?\d{2}\)?\s?9?\d{4}[\s-]?\d{4}(?!\d)"),
    ("CEP", r"\b\d{5}-\d{3}\b"),
    ("RG", r"(?i)\bRG\s*[:\-]?\s*[\dXx.\-]{5,14}"),
]


def deidentify(text: str, identifiers: Optional[PatientIdentifiers] = None) -> DeidentifiedText:
    ids = identifiers or PatientIdentifiers()
    removed: dict[str, int] = {}
    out = text or ""

    def sub(category: str, pattern: str, replacement=None, flags=0) -> None:
        nonlocal out
        def repl(m):
            removed[category] = removed.get(category, 0) + 1
            label = m.groupdict().get("label") if m.groupdict() else None
            return (label + " " if label else "") + f"[{category} REMOVIDO]"
        out = re.sub(pattern, replacement or repl, out, flags=flags)

    for category, pattern in _LABELLED:
        sub(category, pattern)
    for category, pattern in _PATTERNS:
        sub(category, pattern)
    # Supplied identifiers, by exact digits or accent-insensitive words.
    for category, value in (("CPF", ids.cpf), ("RG", ids.rg), ("CARTEIRINHA", ids.card_number), ("TELEFONE", ids.phone)):
        digits = _digits(value)
        if len(digits) >= 5:
            sub(category, r"(?<!\d)" + r"[\s.\-/]?".join(re.escape(d) for d in digits) + r"(?!\d)")
    if ids.birth_date.strip():
        parts = re.findall(r"\d+", ids.birth_date)
        if len(parts) == 3:
            sub("NASCIMENTO", r"(?<!\d)0?" + parts[0].lstrip("0") + r"[/.\-]0?" + parts[1].lstrip("0") + r"[/.\-](?:\d{2})?" + parts[2][-2:] + r"(?!\d)")
    for category, value in (("EMAIL", ids.email), ("ENDERECO", ids.address)):
        if value.strip():
            sub(category, re.escape(value.strip()), flags=re.I)
    words = [w for w in re.split(r"\s+", ids.name.strip()) if len(w) >= 3 and _fold(w) not in {"de", "da", "do", "das", "dos"}]
    words += [w for w in ids.extra if len(w.strip()) >= 3]
    folded = _fold(out)
    for word in sorted(set(words), key=len, reverse=True):
        target = _fold(word)
        positions = [m.span() for m in re.finditer(r"(?<!\w)" + re.escape(target) + r"(?!\w)", folded)]
        for start, end in reversed(positions):
            out = out[:start] + "[NOME REMOVIDO]" + out[end:]
            folded = folded[:start] + _fold("[NOME REMOVIDO]") + folded[end:]
            removed["NOME"] = removed.get("NOME", 0) + 1
    _assert_clean(out, ids, words)
    return DeidentifiedText(out, removed)


def _assert_clean(text: str, ids: PatientIdentifiers, words: list[str]) -> None:
    folded, digits = _fold(text), _digits(text)
    for value in (ids.cpf, ids.rg, ids.card_number, ids.phone):
        d = _digits(value)
        if len(d) >= 5 and d in digits:
            raise DeidentificationRejected("an identifier number survived de-identification")
    for word in words:
        if re.search(r"(?<!\w)" + re.escape(_fold(word)) + r"(?!\w)", folded):
            raise DeidentificationRejected("a patient name part survived de-identification")
    if ids.email.strip() and _fold(ids.email.strip()) in folded:
        raise DeidentificationRejected("e-mail survived de-identification")


_DETECT = {  # field -> labelled pattern; the value follows the label
    "name": dict(_LABELLED)["NOME"],
    "card_number": dict(_LABELLED)["CARTEIRINHA"],
    "birth_date": dict(_LABELLED)["NASCIMENTO"],
    "address": dict(_LABELLED)["ENDERECO"],
    "cpf": r"(?im)(?P<label>\bCPF\s*(?:n[ºo°.]*)?\s*[:\-]?)\s*\d{3}\.?\d{3}\.?\d{3}\s?-?\s?\d{2}\b",
    "rg": r"(?im)(?P<label>\bRG\s*(?:n[ºo°.]*)?\s*[:\-]?)\s*[\dXx.\-]{5,14}",
}


def _cpf_valid(value: str) -> bool:
    d = [int(c) for c in _digits(value)]
    if len(d) != 11 or len(set(d)) == 1:
        return False
    for n in (9, 10):
        if (sum(d[i] * (n + 1 - i) for i in range(n)) * 10 % 11) % 10 != d[n]:
            return False
    return True


def detect_identifiers(text: str) -> dict[str, str]:
    """Find the patient's identifiers in a document so the physician need not type them.

    Deterministic, local, no AI. Only the first labelled value of each field is taken;
    the physician confirms every value before it is used to de-identify the case.
    """
    found: dict[str, str] = {}
    for key, pattern in _DETECT.items():
        for m in re.finditer(pattern, text or ""):
            value = " ".join(m.group(0)[m.end("label") - m.start():].split()).strip(" .,;:-")
            if key == "name" and not re.fullmatch(r"[^\W\d_]+(?:[ '\-][^\W\d_]+)+", value):
                continue
            if key == "cpf" and not _cpf_valid(value):
                continue
            if len(value) >= 3:
                found[key] = value[:200]
                break
    for key, pattern in (("email", dict(_PATTERNS)["EMAIL"]), ("phone", dict(_PATTERNS)["TELEFONE"])):
        m = re.search(pattern, text or "")
        if m:
            found[key] = m.group(0).strip()
    return found
