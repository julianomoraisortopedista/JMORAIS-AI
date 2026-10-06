"""SBOT "Manual de Diretrizes de Codificação em Ortopedia e Traumatologia" as a local index.

Built on the physician's computer from the PDF the SBOT publishes; the manual's content is
not shipped with the code. Each procedure entry keeps what the manual states, verbatim:
ICD-10 codes, indication, character (eletiva/urgência), contraindication, exams of the
indication, CBHPM codes with porte (and the superscript groups the manual marks as
mutually exclusive), OPME with quantities, ICU/ward days, comments, and the page. Nothing
is inferred; fields the parser cannot read are left empty. TUSS equivalence is checked
later against the official ANS table, never assumed.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
import unicodedata

SOURCE = "SBOT — Manual de Diretrizes de Codificação em Ortopedia e Traumatologia"
_ENTRY = re.compile(r"Nome do [Pp]rocedimento\s+(\d{1,2}\.\d{1,3})\s*[—–-]\s*(.+)")
_CBHPM = re.compile(r"^(\d\.\d{2}\.\d{2}\.\d{2}-\d)\s+(.*)$")
_PORTE = re.compile(r"\s(\d{1,2}[A-C])\s*$")
_ICD = re.compile(r"\b[A-TV-Z]\d{2}(?:\.\d{1,2})?\b")
_SUPER = {"¹": "1", "²": "2", "³": "3", "⁴": "4", "⁵": "5"}
_HEADERS = ("Descrição do procedimento", "CIDs do Procedimento", "Indicação", "Caráter da Indicação",
            "Contraindicação", "Exames da Indicação", "Códigos CBHPM", "OPMEs", "Internação", "Anestesia",
            "Resolubilidade", "Seguimento", "Rastreabilidade", "Comentários")


def fold(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", value or "") if not unicodedata.combining(c)).casefold()


@dataclass(frozen=True)
class SbotCode:
    cbhpm: str            # as printed, e.g. 3.07.26.03-4
    description: str
    porte: str
    exclusive_group: str = ""   # superscript marker; codes sharing it are mutually exclusive

    @property
    def digits(self) -> str:
        return re.sub(r"\D", "", self.cbhpm)


@dataclass(frozen=True)
class SbotOpme:
    description: str
    quantity: int


@dataclass(frozen=True)
class SbotEntry:
    entry_id: str          # manual numbering, e.g. 5.19
    name: str
    page: int
    description: str = ""
    icd10: tuple[str, ...] = ()
    indication: str = ""
    character: str = ""
    contraindication: str = ""
    exams: str = ""
    codes: tuple[SbotCode, ...] = ()
    opme: tuple[SbotOpme, ...] = ()
    icu_days: int | None = None
    ward_days: int | None = None
    comments: str = ""

    def as_dict(self) -> dict:
        return asdict(self)

    @property
    def characters(self) -> tuple[str, ...]:
        """Characters the manual allows: ELETIVA, URGENCIA, EMERGENCIA (all when it depends on the case)."""
        text = fold(self.character)
        if "(" in text:
            marked = re.findall(r"\(\s*x\s*\)\s*(eletiv\w*|urgencia|emergencia)", text)
        else:
            marked = re.findall(r"eletiv\w*|urgencia|emergencia", text)
            if not marked or "depende" in text:
                marked = ["eletiva", "urgencia", "emergencia"]
        names = {"eletiva": "ELETIVA", "eletivo": "ELETIVA", "urgencia": "URGENCIA", "emergencia": "EMERGENCIA"}
        return tuple(dict.fromkeys(names.get(m, "ELETIVA") for m in marked))


def _clean_pages(pages: list[str]) -> list[tuple[int, str]]:
    """(page number, line) without running headers and bare page numbers."""
    out = []
    for number, text in enumerate(pages, 1):
        for line in (text or "").splitlines():
            stripped = line.strip()
            if not stripped or re.fullmatch(r"\d{1,3}", stripped) or stripped.startswith("Manual de Diretrizes de Codificação"):
                continue
            out.append((number, stripped))
    return out


def _section(lines: list[str], header: str) -> str:
    """Text after `header` (same line and following lines) until the next known header."""
    for i, line in enumerate(lines):
        if line.startswith(header):
            parts = [line[len(header):].strip()]
            for nxt in lines[i + 1:]:
                if nxt.startswith(_HEADERS):
                    break
                parts.append(nxt)
            return " ".join(p for p in parts if p).strip()
    return ""


def _codes(lines: list[str]) -> tuple[SbotCode, ...]:
    try:
        start = next(i for i, l in enumerate(lines) if l.startswith("Códigos CBHPM"))
    except StopIteration:
        return ()
    codes, pending = [], None
    for line in lines[start + 1:]:
        if line.startswith(("OPMEs", "Internação", "Comentários")):
            break
        m = _CBHPM.match(line)
        if m:
            pending = [m.group(1), m.group(2)]
        elif pending is not None:
            pending[1] += " " + line
        else:
            continue
        porte = _PORTE.search(pending[1])
        if porte:
            text = pending[1][:porte.start()].strip()
            group = "".join(_SUPER.get(c, "") for c in text if c in _SUPER)
            text = "".join(c for c in text if c not in _SUPER).strip()
            codes.append(SbotCode(pending[0], text, porte.group(1), group))
            pending = None
    return tuple(codes)


def _opme(lines: list[str]) -> tuple[SbotOpme, ...]:
    try:
        start = next(i for i, l in enumerate(lines) if l.startswith("OPMEs"))
    except StopIteration:
        return ()
    items, carry = [], ""
    for line in lines[start + 1:]:
        if line.startswith(("Internação", "Anestesia", "Resolubilidade", "Comentários")):
            break
        if line.startswith("Descrição Quantidade") or line == "Descrição":
            continue
        m = re.match(r"^(.*\S)\s+(\d{1,3})$", line)
        if m:
            items.append(SbotOpme(" ".join((carry + " " + m.group(1)).split()), int(m.group(2))))
            carry = ""
        else:
            carry = (carry + " " + line).strip()
    return tuple(items)


def parse_manual(pages: list[str]) -> list[SbotEntry]:
    lines = _clean_pages(pages)
    starts = [i for i, (_, l) in enumerate(lines) if _ENTRY.match(l)]
    entries = []
    for n, start in enumerate(starts):
        block = lines[start:starts[n + 1] if n + 1 < len(starts) else len(lines)]
        m = _ENTRY.match(block[0][1])
        name = m.group(2).strip()
        body = [l for _, l in block[1:]]
        if body and not body[0].startswith(_HEADERS) and body[0].upper() == body[0]:
            name += " " + body.pop(0)  # title wrapped to the next line
        stay = re.search(r"UTI\s+(\d+)\s*dia\(s\)\s*Quarto\s+(\d+)\s*dia\(s\)", " ".join(body))
        icd_text = _section(body, "CIDs do Procedimento")
        entries.append(SbotEntry(
            entry_id=m.group(1), name=" ".join(name.split()), page=block[0][0],
            description=_section(body, "Descrição do procedimento")[:3000],
            icd10=tuple(dict.fromkeys(_ICD.findall(icd_text))),
            indication=_section(body, "Indicação")[:2000],
            character=_section(body, "Caráter da Indicação")[:80],
            contraindication=_section(body, "Contraindicação")[:500],
            exams=_section(body, "Exames da Indicação")[:500],
            codes=_codes(body), opme=_opme(body),
            icu_days=int(stay.group(1)) if stay else None, ward_days=int(stay.group(2)) if stay else None,
            comments=_section(body, "Comentários")[:1500]))
    return entries


def build_index(pdf_path: Path, output: Path) -> dict:
    from pypdf import PdfReader  # optional dependency, used only to build the index
    data = Path(pdf_path).read_bytes()
    reader = PdfReader(pdf_path)
    entries = parse_manual([page.extract_text() or "" for page in reader.pages])
    payload = {"source": SOURCE, "sha256": hashlib.sha256(data).hexdigest(), "pages": len(reader.pages),
               "entries": [e.as_dict() for e in entries]}
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(output)
    return {"entries": len(entries), "with_codes": sum(1 for e in entries if e.codes),
            "with_opme": sum(1 for e in entries if e.opme)}


def _entry(d: dict) -> SbotEntry:
    return SbotEntry(**{**d, "icd10": tuple(d["icd10"]), "codes": tuple(SbotCode(**c) for c in d["codes"]),
                        "opme": tuple(SbotOpme(**o) for o in d["opme"])})


class SbotIndex:
    """Read-only lookups over the built index."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._data = json.loads(self.path.read_text(encoding="utf-8"))
        self._entries = [_entry(d) for d in self._data["entries"]]

    def version(self) -> str:
        return f"{self._data['pages']} páginas, sha256 {self._data['sha256'][:12]}"

    def get(self, entry_id: str) -> SbotEntry | None:
        return next((e for e in self._entries if e.entry_id == entry_id), None)

    def search(self, query: str, limit: int = 20) -> list[SbotEntry]:
        terms = [t for t in re.split(r"\W+", fold(query)) if len(t) >= 2]
        digits = re.sub(r"\D", "", query)
        scored = []
        for e in self._entries:
            hay = fold(e.name + " " + " ".join(c.description for c in e.codes))
            score = sum(3 if t in fold(e.name) else 1 for t in terms if t in hay)
            if len(digits) >= 6 and any(c.digits.startswith(digits) for c in e.codes):
                score += 10
            if terms and all(t in hay for t in terms):
                score += 5
            if score:
                scored.append((score, e))
        scored.sort(key=lambda x: (-x[0], x[1].entry_id))
        return [e for _, e in scored[:limit]]

    def for_tuss(self, tuss_code: str) -> list[SbotEntry]:
        """Entries whose CBHPM codes include this code (digits compared verbatim)."""
        return [e for e in self._entries if any(c.digits == tuss_code for c in e.codes)]
