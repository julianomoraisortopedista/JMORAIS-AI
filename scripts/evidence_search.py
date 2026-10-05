#!/usr/bin/env python3
"""Read-only scientific discovery for one clinical question (PubMed + Crossref).

Uses only the public discovery boundary of the authoritative reconciliation
pipeline. Output is a list of CANDIDATES: it is never trusted evidence, carries
no support direction (supporting/opposing) and no Vancouver text. Those require
ledger-backed package issuance and human appraisal. Never pass patient data.
"""
from __future__ import annotations

import argparse
import json
import sys

from jmoraIs.application.evidence_query import (
    STUDY_DESIGN_FILTERS,
    BuiltEvidenceQuery,
    EvidenceQueryRejected,
    PICOQuestion,
    build_pubmed_query,
)
from jmoraIs.application.scientific_verification import (
    AuthoritativeReconciliationPipeline,
    ScientificDiscoveryResult,
    ScientificVerificationInput,
)
from jmoraIs.connect.crossref import CrossrefConnector
from jmoraIs.connect.pubmed import PubMedConnector

NOTICE = ("CANDIDATES ONLY - not trusted evidence; not classified as supporting/opposing; "
          "physician appraisal required before any clinical or insurer use.")


def discover(query: str, pipeline: AuthoritativeReconciliationPipeline | None = None) -> ScientificDiscoveryResult:
    pipeline = pipeline or AuthoritativeReconciliationPipeline(pubmed=PubMedConnector(), crossref=CrossrefConnector())
    return pipeline.discover(ScientificVerificationInput(query=query))


def verify_identifiers(pmids: tuple[str, ...], dois: tuple[str, ...],
                       pipeline: AuthoritativeReconciliationPipeline | None = None) -> ScientificDiscoveryResult:
    """Check identifiers brought from other sources (e.g. read manually elsewhere) against PubMed/Crossref."""
    pipeline = pipeline or AuthoritativeReconciliationPipeline(pubmed=PubMedConnector(), crossref=CrossrefConnector())
    requests_ = [ScientificVerificationInput(pmid=v) for v in pmids] + [ScientificVerificationInput(doi=v) for v in dois]
    results = [pipeline.discover(request) for request in requests_]
    articles, seen = [], set()
    for article in (a for r in results for a in r.articles):
        keys = {k for k in (article.pmid and "pmid:" + article.pmid,
                            article.doi and "doi:" + article.doi.casefold()) if k}
        if keys and keys & seen:
            continue
        seen |= keys
        articles.append(article)
    return ScientificDiscoveryResult(search_id=",".join(r.search_id for r in results), articles=tuple(articles))


def split_terms(value: str | None) -> tuple[str, ...]:
    return tuple(term.strip() for term in (value or "").split(";") if term.strip())


def build_query(args: argparse.Namespace, pubmed: PubMedConnector | None = None) -> BuiltEvidenceQuery:
    if args.population or args.intervention or args.comparison or args.outcome or args.design:
        if args.query:
            raise EvidenceQueryRejected("use either a free-text query or PICO options, not both")
        question = PICOQuestion(split_terms(args.population), split_terms(args.intervention),
            split_terms(args.comparison), split_terms(args.outcome),
            tuple(d.strip() for d in (args.design or "").split(",") if d.strip()))
        pubmed = pubmed or PubMedConnector()
        return build_pubmed_query(question, None if args.no_mesh else pubmed.mesh_headings_for)
    query = (args.query or "").strip()
    if not query:
        raise EvidenceQueryRejected("a query or --population/--intervention is required")
    return BuiltEvidenceQuery(query)


def render_text(query: str, result: ScientificDiscoveryResult, built: BuiltEvidenceQuery | None = None) -> str:
    lines = [f"Query: {query}"]
    for item in (built.expansions if built else ()):
        lines.append(f"  MeSH: {item.element} '{item.synonym}' -> {item.mesh_heading}")
    lines += [f"Search run: {result.search_id}", NOTICE, ""]
    if not result.articles:
        lines.append("No candidate articles returned by PubMed.")
    for index, article in enumerate(result.articles, 1):
        lines.append(f"{index}. {article.title or '[title unavailable]'}")
        identifiers = [f"PMID {article.pmid}" if article.pmid else None,
                       f"DOI {article.doi}" if article.doi else None,
                       f"PMCID {article.pmcid}" if article.pmcid else None]
        lines.append("   " + " | ".join(value for value in identifiers if value) if any(identifiers) else "   [no identifier]")
        if article.pmid:
            lines.append(f"   https://pubmed.ncbi.nlm.nih.gov/{article.pmid}/")
    return "\n".join(lines)


def render_json(query: str, result: ScientificDiscoveryResult, built: BuiltEvidenceQuery | None = None) -> str:
    return json.dumps({
        "query": query, "search_id": result.search_id, "trusted_evidence": result.trusted_evidence,
        "mesh_expansions": [dict(element=e.element, synonym=e.synonym, mesh_heading=e.mesh_heading)
                            for e in (built.expansions if built else ())],
        "notice": NOTICE,
        "candidates": [dict(article_id=a.article_id, title=a.title, pmid=a.pmid, doi=a.doi, pmcid=a.pmcid)
                       for a in result.articles],
    }, ensure_ascii=False, indent=2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("query", nargs="?", help="Free-text PubMed query (no patient identifiers)")
    parser.add_argument("--population", help="Synonyms separated by ';' (English), e.g. 'knee osteoarthritis'")
    parser.add_argument("--intervention", help="Synonyms separated by ';'")
    parser.add_argument("--comparison", help="Synonyms separated by ';'")
    parser.add_argument("--outcome", help="Synonyms separated by ';'")
    parser.add_argument("--design", help="Comma list of: " + ", ".join(STUDY_DESIGN_FILTERS))
    parser.add_argument("--no-mesh", action="store_true", help="Do not add MeSH headings")
    parser.add_argument("--pmid", help="Verify PMIDs (comma list) brought from another source")
    parser.add_argument("--doi", help="Verify DOIs (comma list) brought from another source")
    parser.add_argument("--json", action="store_true", help="Machine-readable output")
    args = parser.parse_args(argv)
    if args.pmid or args.doi:
        if args.query or args.population or args.intervention or args.comparison or args.outcome or args.design:
            parser.error("use --pmid/--doi alone")
        pmids = tuple(v.strip() for v in (args.pmid or "").split(",") if v.strip())
        dois = tuple(v.strip() for v in (args.doi or "").split(",") if v.strip())
        label = "identifiers: " + ", ".join(pmids + dois)
        result = verify_identifiers(pmids, dois)
        print(render_json(label, result) if args.json else render_text(label, result))
        return 0
    try:
        built = build_query(args)
    except EvidenceQueryRejected as exc:
        parser.error(str(exc))
    result = discover(built.query)
    print(render_json(built.query, result, built) if args.json else render_text(built.query, result, built))
    return 0


if __name__ == "__main__":
    sys.exit(main())
