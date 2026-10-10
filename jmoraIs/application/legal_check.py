"""Which norms cited in a physician's text are in the verified legal library.

Physician-written or edited text (report, request, contestation) may cite norms the
system never checked, for example a paraphrase of RN 424/2017 that its text does not
support. This finds norm references (RN, Lei, Resolução CFM, RDC, ADI, Súmula) and marks
each as VERIFIED when the same norm is among the sources the drafters may cite
(`appeal_drafting.legal_sources`, official excerpts or ANS-published wording), otherwise
NOT_VERIFIED. It checks the norm, not the wording: a verified norm can still be misquoted,
so the physician compares the sentence with the excerpt shown.
"""
from __future__ import annotations

import re

_N = r"n(?:º|°|o|\.)?\s*"
PATTERNS = (
    ("RN", rf"(?i)\b(?:RN|Resolu[cç][aã]o\s+Normativa)\s*(?:ANS\s*)?(?:{_N})?(\d{{1,4}})\s*/\s*(\d{{2,4}})"),
    ("LEI", rf"(?i)\bLei\s*(?:Federal\s*)?(?:{_N})?([\d.]{{3,7}})\s*/\s*(\d{{2,4}})"),
    ("CFM", rf"(?i)\b(?:Resolu[cç][aã]o\s+CFM|CFM,?\s*Resolu[cç][aã]o|CFM)\s*(?:{_N})?([\d.]{{3,7}})\s*/\s*(\d{{2,4}})"),
    ("RDC", rf"(?i)\bRDC\s*(?:ANVISA\s*)?(?:{_N})?(\d{{1,4}})\s*/\s*(\d{{2,4}})"),
    ("ADI", r"(?i)\bADI\s*(?:n(?:º|°|o|\.)?\s*)?([\d.]{3,6})"),
    ("SUMULA", r"(?i)\bS[uú]mula\s*(?:n(?:º|°|o|\.)?\s*)?(\d{1,4})"),
)


def _year(value: str) -> str:
    return value if len(value) == 4 else ("19" + value if int(value) > 30 else "20" + value)


def _keys(text: str):
    for kind, pattern in PATTERNS:
        for m in re.finditer(pattern, text or ""):
            groups = [g for g in m.groups() if g]
            number = groups[0].replace(".", "").lstrip("0")
            key = f"{kind} {number}" + (f"/{_year(groups[1])}" if len(groups) > 1 else "")
            yield key, m.group(0).strip(), m.start()


def verified_sources() -> dict[str, list[tuple[str, str]]]:
    """Norm key -> [(citation, excerpt)] of the sources the drafters may cite."""
    from jmoraIs.application.appeal_drafting import legal_sources
    found: dict[str, list[tuple[str, str]]] = {}
    for citation, excerpt in legal_sources().values():
        for key in dict.fromkeys(k for k, _, _ in _keys(citation)):
            found.setdefault(key, []).append((citation, excerpt))
    return found


def verified_keys() -> set[str]:
    return set(verified_sources())


def check_citations(text: str) -> list[dict]:
    known, seen, out = verified_sources(), set(), []
    for key, cited, start in _keys(text):
        if key in seen:
            continue
        seen.add(key)
        sentence = re.split(r"(?<=[.!?])\s+", (text or "")[max(0, start - 200):start + 300])
        context = next((s for s in sentence if cited in s), cited)
        out.append({"norm": key, "cited": cited, "status": "VERIFIED" if key in known else "NOT_VERIFIED",
                    "sentence": " ".join(context.split())[:400],
                    "sources": [dict(citation=c, excerpt=e) for c, e in known.get(key, [])][:3]})
    return out
