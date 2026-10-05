"""Regression cases taken from real PubMed vs Crossref records (2026-10-05)."""
import pytest

from jmoraIs.connect.crossref import CrossrefConnector
from jmoraIs.connect.pubmed import PubMedConnector
from jmoraIs.verification import _author_key, normalize_journal, normalize_article, reconcile_with_crossref, titles_match
from tests.test_crossref_connector import FakeHttpClient, FakeResponse
from tests.test_strict_vancouver_gate import article, formatter_for


@pytest.mark.parametrize("pubmed,crossref", [
    ("Skou ST", "Skou, Søren T."),            # PubMed initials vs Crossref given name, diacritics
    ("Arendt-Nielsen L", "Arendt-Nielsen, Lars"),
    ("Raaij van TM", "van Raaij, Tom M"),      # inverted particle
    ("De Bie R", "de Bie, Rob"),
    ("Zeni J Jr", "Zeni Jr, Joseph"),          # generational suffix
    ("Smith J III", "Smith, John"),
    ("Müller A", "Muller, Anna"),
    ("Doe J", "Jane Doe"),                     # legacy "Given Family" strings
    ("Doe, Jane", "Jane Doe"),
])
def test_same_author_in_different_formats_matches(pubmed, crossref):
    assert _author_key([pubmed]) == _author_key([crossref])


@pytest.mark.parametrize("pubmed,crossref", [
    ("Doe J", "Smith, John"), ("Doe J", "Doe, Mary"), ("El Mansy Y", "Mansy, Y"),
])
def test_different_or_discrepant_authors_still_conflict(pubmed, crossref):
    assert _author_key([pubmed]) != _author_key([crossref])


def test_collective_author_is_ignored_but_person_lists_must_match():
    pubmed = ["Jette DU", "Zeni J Jr", "American Physical Therapy Association"]
    assert _author_key(pubmed) == _author_key(["Jette, Diane U", "Zeni Jr, Joseph"])
    assert _author_key(pubmed) != _author_key(["Jette, Diane U"])


@pytest.mark.parametrize("left,right", [
    ("The New England journal of medicine", "New England Journal of Medicine"),
    ("The Journal of orthopaedic and sports physical therapy", "Journal of Orthopaedic &amp; Sports Physical Therapy"),
    ("Knee surgery, sports traumatology, arthroscopy : official journal of the ESSKA", "Knee Surgery, Sports Traumatology, Arthroscopy"),
    ("Orthopadie (Heidelberg, Germany)", "Die Orthopädie"),
])
def test_journal_name_variants_match(left, right):
    assert normalize_journal(left) == normalize_journal(right)


def test_different_journals_do_not_match():
    assert normalize_journal("The Knee") != normalize_journal("Knee Surgery, Sports Traumatology, Arthroscopy")


@pytest.mark.parametrize("left,right,expected", [
    ("Assessment of Outcomes of Inpatient or Clinic-Based vs Home-Based Rehabilitation After Total Knee Arthroplasty: A Systematic Review and Meta-analysis.",
     "Assessment of Outcomes of Inpatient or Clinic-Based vs Home-Based Rehabilitation After Total Knee Arthroplasty", True),
    ("2-year follow-up report on micromotion of a short tibia stem. A prospective, randomized RSA study of 59 patients.",
     "2-year follow-up report on micromotion of a short tibia stem", True),
    ("A Randomized, Controlled Trial of Total Knee Replacement.", "A Randomized, Controlled Trial of Total Knee Replacement", True),
    ("[Prehabilitation before total knee arthroplasty].", "Prähabilitation vor Knieendoprothetik", False),
    ("Knee pain: a review", "Knee pain", False),  # main title too short to accept a subtitle-only difference
    ("Total knee replacement in older adults", "Total knee replacement in younger adults", False),
])
def test_title_subtitle_tolerance_is_bounded(left, right, expected):
    assert titles_match(left, right) is expected


def test_crossref_print_year_resolves_online_first_difference():
    payload = {"message": {"DOI": "10.1/x", "title": ["T"], "container-title": ["J"],
                           "issued": {"date-parts": [[2018, 3, 8]]}, "published-online": {"date-parts": [[2018, 3, 8]]},
                           "published-print": {"date-parts": [[2019, 3]]},
                           "author": [{"given": "Tom M", "family": "van Raaij"}, {"name": "Study Group"}]}}
    metadata = CrossrefConnector(http_client=FakeHttpClient(FakeResponse(payload))).search_by_doi("10.1/x").authoritative_metadata
    assert metadata["year"] == 2018 and metadata["year_candidates"] == (2018, 2019)
    assert metadata["authors"] == ["van Raaij, Tom M", "Study Group"]
    record = normalize_article({"title": "T", "journal": "J", "year": 2019, "authors": ["Raaij van TM"], "pmid": "1"})
    assert "year" not in ((reconcile_with_crossref(record, metadata).raw_metadata or {}).get("crossref_conflicts") or [])
    other = normalize_article({"title": "T", "journal": "J", "year": 2016, "authors": ["Raaij van TM"], "pmid": "1"})
    assert "year" in reconcile_with_crossref(other, metadata).raw_metadata["crossref_conflicts"]


def test_pubmed_summary_supplies_volume_issue_pages_and_nlm_abbreviation():
    class Client:
        def get(self, url, params=None, timeout=None):
            return FakeResponse({"result": {"26488691": {
                "uid": "26488691", "title": "A Randomized, Controlled Trial of Total Knee Replacement.",
                "fulljournalname": "The New England journal of medicine", "source": "N Engl J Med",
                "volume": "373", "issue": "17", "pages": "1597-606", "pubdate": "2015 Oct 22",
                "authors": [{"name": "Skou ST"}], "articleids": [{"idtype": "doi", "value": "10.1056/NEJMoa1505467"}]}}})
    metadata = PubMedConnector(Client(), min_interval=0).search_by_pmid("26488691").authoritative_metadata
    assert (metadata["journal_abbreviation"], metadata["volume"], metadata["issue"], metadata["pages"]) == (
        "N Engl J Med", "373", "17", "1597-606")
    record = normalize_article(metadata)
    assert (record.journal_abbreviation, record.volume, record.issue, record.pages) == ("N Engl J Med", "373", "17", "1597-606")


def test_vancouver_uses_nlm_abbreviation_and_single_title_period():
    record = article(title="Verified study.", journal="The Medical Journal", journal_abbreviation="Med J",
                     volume="12", issue="3", pages="10-18", doi="10.1/abc")
    formatter, package_id = formatter_for(record)
    assert formatter.render(package_id=package_id, article=record).rendered_text == (
        "Doe J, Smith A. Verified study. Med J. 2025;12(3):10-18. doi: 10.1/abc.")
