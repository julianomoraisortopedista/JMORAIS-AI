"""Deterministic PICO -> PubMed query construction with traceable MeSH expansion.

Each PICO element is a concept made of user-supplied synonyms. A concept becomes
an OR-group of the synonyms as [tiab] plus any MeSH heading that PubMed's own
Automatic Term Mapping assigns to a *whole* synonym (word-level splits are
ignored as too broad). Concepts are ANDed; study designs become [pt] filters.
The returned provenance records every MeSH heading and the synonym it came from.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Callable, Optional

STUDY_DESIGN_FILTERS: dict[str, str] = {
    "rct": "randomized controlled trial[pt]",
    "sr": "systematic review[pt]",
    "ma": "meta-analysis[pt]",
    "guideline": "practice guideline[pt]",
}
# Letters (any language), digits, space and a few safe separators; no quotes,
# brackets, wildcards or boolean syntax can be injected into the query.
_SAFE_TERM = re.compile(r"^[^\W_](?:[\w \-',./]*[\w.])?$", re.UNICODE)
_RESERVED = re.compile(r"\b(AND|OR|NOT)\b")

MeshLookup = Callable[[str], tuple[str, ...]]


class EvidenceQueryRejected(ValueError):
    pass


@dataclass(frozen=True)
class MeshExpansion:
    element: str
    synonym: str
    mesh_heading: str


@dataclass(frozen=True)
class PICOQuestion:
    population: tuple[str, ...]
    intervention: tuple[str, ...]
    comparison: tuple[str, ...] = ()
    outcome: tuple[str, ...] = ()
    designs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.population or not self.intervention:
            raise EvidenceQueryRejected("population and intervention are required")
        for name in ("population", "intervention", "comparison", "outcome"):
            for term in getattr(self, name):
                if not isinstance(term, str) or not _SAFE_TERM.match(term.strip()) or _RESERVED.search(term):
                    raise EvidenceQueryRejected(f"unsafe or empty {name} term")
        unknown = set(self.designs) - set(STUDY_DESIGN_FILTERS)
        if unknown:
            raise EvidenceQueryRejected("unknown study design: " + ", ".join(sorted(unknown)))


@dataclass(frozen=True)
class BuiltEvidenceQuery:
    query: str
    expansions: tuple[MeshExpansion, ...] = field(default_factory=tuple)


def build_pubmed_query(question: PICOQuestion, mesh_lookup: Optional[MeshLookup] = None) -> BuiltEvidenceQuery:
    if not isinstance(question, PICOQuestion):
        raise EvidenceQueryRejected("typed PICOQuestion is required")
    groups: list[str] = []
    expansions: list[MeshExpansion] = []
    for element in ("population", "intervention", "comparison", "outcome"):
        terms = tuple(dict.fromkeys(term.strip() for term in getattr(question, element)))
        if not terms:
            continue
        parts: list[str] = []
        for term in terms:
            for heading in (mesh_lookup(term) if mesh_lookup else ()):
                clause = f'"{heading}"[MeSH Terms]'
                if clause not in parts:
                    parts.append(clause)
                    expansions.append(MeshExpansion(element, term, heading))
            parts.append(f'"{term}"[tiab]')
        groups.append("(" + " OR ".join(parts) + ")")
    if question.designs:
        designs = tuple(dict.fromkeys(question.designs))
        groups.append("(" + " OR ".join(STUDY_DESIGN_FILTERS[d] for d in designs) + ")")
    return BuiltEvidenceQuery(" AND ".join(groups), tuple(expansions))
