from dataclasses import replace
from datetime import datetime, timezone
import json

import pytest

from jmoraIs.application.evidence_packages import ScientificEvidencePackagePort
from jmoraIs.application.scientific_justification import JustificationRejected, build_justification, render_markdown
from jmoraIs.application.scientific_verification import AuthoritativeReconciliationPipeline
from jmoraIs.connect.pubmed import AbstractUnavailable
from jmoraIs.infrastructure import InMemoryPackageCatalogRepository
from jmoraIs.scientific_domain import ExistenceVerificationStatus, IdentifierVerificationResult, SupportDirection
from scripts import build_justification as cli
from tests.test_support_classification import CLAIM, QUOTE, abstract

NOW = datetime(2026, 10, 5, tzinfo=timezone.utc)
META = {"pmid": "26488691", "doi": "10.1056/NEJMoa1505467", "title": "A Randomized, Controlled Trial of Total Knee Replacement.",
        "journal": "The New England journal of medicine", "journal_abbreviation": "N Engl J Med", "volume": "373",
        "issue": "17", "pages": "1597-606", "year": 2015, "authors": ["Skou ST", "Roos EM"]}
CROSSREF = {"doi": "10.1056/NEJMoa1505467", "title": "A Randomized, Controlled Trial of Total Knee Replacement",
            "journal": "New England Journal of Medicine", "year": 2015, "year_candidates": (2015,),
            "authors": ["Skou, Søren T.", "Roos, Ewa M."]}


def result(source, value, metadata, kind="PMID"):
    return IdentifierVerificationResult(kind, value, True, ExistenceVerificationStatus.CONFIRMED.value, source,
                                        source_locator="https://x/" + value, checked_at=NOW, authoritative_metadata=metadata)


class PubMed:
    def __init__(self, metadata=META, abstracts=None):
        self.metadata, self.abstracts = metadata, abstracts if abstracts is not None else {"26488691": abstract()}

    def fetch_abstract(self, pmid):
        if pmid not in self.abstracts:
            raise AbstractUnavailable("no abstract published for this PMID")
        return self.abstracts[pmid]

    def search_by_pmid(self, pmid):
        return result("NCBI PubMed", pmid, {**self.metadata, "pmid": pmid})

    def search_by_doi(self, doi):
        return result("NCBI PubMed", doi, self.metadata, "DOI")

    def search_by_title(self, title):
        return []


class Crossref:
    def __init__(self, metadata=CROSSREF):
        self.metadata = metadata

    def search_by_doi(self, doi):
        return result("Crossref", doi, self.metadata, "DOI")


def record(**changes):
    base = dict(pmid="26488691", claim=CLAIM, source="https://pubmed.ncbi.nlm.nih.gov/26488691/",
                abstract_sha256=abstract().content_hash, ai_status="PENDING_PHYSICIAN_REVIEW", ai_direction="SUPPORTING",
                quote=QUOTE, ai_rationale="r", model="claude-opus-5-5", prompt_version="prompt_1",
                physician_decision="ACCEPT", final_direction="SUPPORTING", reviewer="CRM-SP-1", note="",
                decided_at=NOW.isoformat())
    base.update(changes)
    return base


def build(records, pubmed=None, crossref=None, claim=CLAIM):
    pubmed = pubmed or PubMed()
    packages = ScientificEvidencePackagePort(catalog=InMemoryPackageCatalogRepository(), clock=lambda: NOW)
    pipeline = AuthoritativeReconciliationPipeline(pubmed=pubmed, crossref=crossref or Crossref(), packages=packages, clock=lambda: NOW)
    return build_justification(claim, records, pubmed=pubmed, pipeline=pipeline, packages=packages, clock=lambda: NOW)


def test_confirmed_verified_evidence_becomes_numbered_vancouver_reference():
    draft = build([record()])
    (ref,) = draft.references
    assert ref.direction is SupportDirection.SUPPORTING and ref.quote == QUOTE and ref.reviewer == "CRM-SP-1"
    assert ref.vancouver == ("Skou ST, Roos EM. A Randomized, Controlled Trial of Total Knee Replacement. "
                             "N Engl J Med. 2015;373(17):1597-606. doi: 10.1056/NEJMoa1505467.")
    text = render_markdown(draft)
    assert "RASCUNHO PARA REVISÃO MÉDICA" in text and f'[1] PMID 26488691: "{QUOTE}"' in text
    assert "1 a favor, 0 contrárias, 0 neutras, 0 inconclusivas" in text and "1. Skou ST" in text


@pytest.mark.parametrize("changes,reason", [
    (dict(physician_decision="REJECT", final_direction=None), "rejeitado pelo médico"),
    (dict(abstract_sha256="0" * 64), "o resumo mudou"),
    (dict(quote="Total knee replacement is always better than any treatment"), "não é literal"),
    (dict(claim="A different claim about hips"), "outra afirmação"),
    (dict(pmid="11111111"), "resumo indisponível"),
    (dict(final_direction="MAYBE"), "registro de decisão inválido"),
])
def test_unusable_items_are_excluded_with_reason(changes, reason):
    draft = build([record(**changes)])
    assert draft.references == () and reason in draft.excluded[0].reason
    assert reason in render_markdown(draft)


def test_unverified_metadata_is_excluded_not_cited():
    draft = build([record()], crossref=Crossref({**CROSSREF, "journal": "The Lancet"}))
    assert draft.references == () and "não VERIFICADOS" in draft.excluded[0].reason


def test_opposing_and_neutral_evidence_are_kept_and_duplicates_dropped():
    second = replace(abstract(), pmid="22222222", source_locator="https://pubmed.ncbi.nlm.nih.gov/22222222/")
    pubmed = PubMed(abstracts={"26488691": abstract(), "22222222": second})
    draft = build([record(), record(), record(pmid="22222222", final_direction="OPPOSING", physician_decision="OVERRIDE",
                                             note="Primary outcome not met")], pubmed=pubmed)
    assert [r.direction for r in draft.references] == [SupportDirection.SUPPORTING, SupportDirection.OPPOSING]
    assert [r.number for r in draft.references] == [1, 2]
    assert draft.excluded[0].reason == "decisão duplicada para o mesmo PMID"
    text = render_markdown(draft)
    assert "## Evidências contrárias (1)" in text and "## Evidências neutras (0)" in text


def test_claim_is_required():
    with pytest.raises(JustificationRejected):
        build([record()], claim="x")


def test_cli_writes_private_markdown(tmp_path):
    decisions = tmp_path / "d.json"
    decisions.write_text(json.dumps([record()]))
    out, lines = tmp_path / "j.md", []
    assert cli.main(["--decisions", str(decisions), "--out", str(out)], pubmed=PubMed(), crossref=Crossref(),
                    write=lines.append) == 0
    assert "1 reference(s) included, 0 excluded" in lines[0] and "N Engl J Med" in out.read_text()
    assert oct(out.stat().st_mode & 0o777) == "0o600"


def test_cli_rejects_mixed_claims_and_bad_files(tmp_path):
    decisions = tmp_path / "d.json"
    decisions.write_text(json.dumps([record(), record(claim="Another claim about something else")]))
    with pytest.raises(SystemExit):
        cli.main(["--decisions", str(decisions), "--out", str(tmp_path / "j.md")], pubmed=PubMed(), crossref=Crossref())
    decisions.write_text("{}")
    with pytest.raises(SystemExit):
        cli.main(["--decisions", str(decisions), "--out", str(tmp_path / "j.md")], pubmed=PubMed(), crossref=Crossref())


def test_cli_with_procedure_adds_legal_section_and_printable_html(tmp_path):
    decisions = tmp_path / "d.json"
    decisions.write_text(json.dumps([record()]))
    summary = tmp_path / "s.txt"
    summary.write_text("Dor refratária ao tratamento conservador.")
    out, page, lines = tmp_path / "j.md", tmp_path / "doc.html", []
    assert cli.main(["--decisions", str(decisions), "--out", str(out), "--procedure", "Artroplastia total do joelho",
                     "--rol", "NAO", "--ans-analysis", "SEM_ANALISE", "--crm", "CRM-SP 1", "--html", str(page),
                     "--clinical-summary-file", str(summary)], pubmed=PubMed(), crossref=Crossref(), write=lines.append) == 0
    assert "## Fundamentação jurídica" in out.read_text() and "Dor refratária" in page.read_text()
    assert any(line.startswith("PENDING:") for line in lines) and oct(page.stat().st_mode & 0o777) == "0o600"
    with pytest.raises(SystemExit):
        cli.main(["--decisions", str(decisions), "--out", str(out), "--html", str(page)], pubmed=PubMed(), crossref=Crossref())
