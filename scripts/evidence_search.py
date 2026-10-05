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


def render_text(query: str, result: ScientificDiscoveryResult) -> str:
    lines = [f"Query: {query}", f"Search run: {result.search_id}", NOTICE, ""]
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


def render_json(query: str, result: ScientificDiscoveryResult) -> str:
    return json.dumps({
        "query": query, "search_id": result.search_id, "trusted_evidence": result.trusted_evidence,
        "notice": NOTICE,
        "candidates": [dict(article_id=a.article_id, title=a.title, pmid=a.pmid, doi=a.doi, pmcid=a.pmcid)
                       for a in result.articles],
    }, ensure_ascii=False, indent=2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("query", help="Clinical question or PubMed query (no patient identifiers)")
    parser.add_argument("--json", action="store_true", help="Machine-readable output")
    args = parser.parse_args(argv)
    query = args.query.strip()
    if not query:
        parser.error("query is required")
    result = discover(query)
    print(render_json(query, result) if args.json else render_text(query, result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
