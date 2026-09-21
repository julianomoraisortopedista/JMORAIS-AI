from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from .models import BenchmarkRecord, ReconciliationResult, SourceObservation

PMID_RE = re.compile(r"^[1-9][0-9]{0,8}$")
PMCID_RE = re.compile(r"^PMC[1-9][0-9]{0,8}$", re.IGNORECASE)
DOI_RE = re.compile(r"^10\.\d{4,9}/[-._;()/:A-Z0-9]+$", re.IGNORECASE)


def valid_pmid(value: str | None) -> bool:
    return bool(value and PMID_RE.fullmatch(value.strip()))


def valid_pmcid(value: str | None) -> bool:
    return value is None or bool(PMCID_RE.fullmatch(value.strip()))


def normalize_doi(value: str | None) -> str:
    if not value:
        return ""
    cleaned = value.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :]
    return cleaned.rstrip(". ")


def valid_doi(value: str | None) -> bool:
    return bool(DOI_RE.fullmatch(normalize_doi(value)))


def normalize_text(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def normalize_citation(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).rstrip(".")


def citation_identity(record: BenchmarkRecord) -> tuple[str, str]:
    if valid_doi(record.doi):
        return ("doi", normalize_doi(record.doi))
    if valid_pmid(record.pmid):
        return ("pmid", record.pmid)
    if record.pmcid and valid_pmcid(record.pmcid):
        return ("pmcid", record.pmcid.upper())
    return ("metadata", f"{normalize_text(record.title)}|{record.year}")


def find_duplicates(records: Iterable[BenchmarkRecord]) -> dict[str, str]:
    seen: dict[tuple[str, str], str] = {}
    duplicates: dict[str, str] = {}
    for record in records:
        identity = citation_identity(record)
        if identity in seen:
            duplicates[record.record_id] = seen[identity]
        else:
            seen[identity] = record.record_id
    return duplicates


def validate_vancouver(record: BenchmarkRecord) -> bool:
    rendered = normalize_text(normalize_citation(record.vancouver))
    required = [record.title, record.journal, str(record.year)]
    if record.authors:
        required.append(record.authors[0].split()[0])
    return bool(record.vancouver.strip()) and all(
        normalize_text(value) in rendered for value in required
    )


def reconcile(record: BenchmarkRecord) -> ReconciliationResult:
    fields = ("title", "journal", "year", "pmid", "pmcid", "doi")
    agreement: dict[str, bool] = {}
    conflicts: dict[str, tuple[str, ...]] = {}
    for field in fields:
        expected = getattr(record, field)
        values = [getattr(item, field) for item in record.observations]
        values = [value for value in values if value not in (None, "")]
        if field == "doi":
            normalized = [normalize_doi(str(value)) for value in values]
            expected_value = normalize_doi(str(expected))
        elif field in {"title", "journal"}:
            normalized = [normalize_text(str(value)) for value in values]
            expected_value = normalize_text(str(expected))
        else:
            normalized = [str(value).upper() for value in values]
            expected_value = str(expected).upper()
        agreement[field] = bool(normalized) and all(value == expected_value for value in normalized)
        distinct = tuple(sorted(set(normalized)))
        if len(distinct) > 1 or (normalized and expected_value not in distinct):
            conflicts[field] = distinct

    coverage = tuple(sorted({item.source for item in record.observations}))
    critical = agreement["title"] and agreement["doi"] and agreement["pmid"]
    score = sum(agreement.values()) / len(agreement)
    source_factor = min(len(coverage) / 4, 1.0)
    confidence = round(0.8 * score + 0.2 * source_factor, 4)
    identity_conflict = any(field in conflicts for field in ("title", "doi", "pmid"))
    return ReconciliationResult(
        matched=critical and not identity_conflict,
        field_agreement=agreement,
        conflicts=conflicts,
        source_coverage=coverage,
        confidence=confidence,
    )
