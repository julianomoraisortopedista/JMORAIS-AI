#!/usr/bin/env python3
"""Start the local physician workbench at http://127.0.0.1:8770 (this computer only)."""
from __future__ import annotations

import argparse

import uvicorn

from jmoraIs.application.support_classification_runtime import save_keychain_api_key
from jmoraIs.connect.crossref import CrossrefConnector
from jmoraIs.connect.pubmed import PubMedConnector
from jmoraIs.workbench.app import (
    create_app, default_case_extractor_factory, default_classifier_factory, default_question_translator_factory,
    default_report_writer_factory,
)


STATE = __import__("pathlib").Path.home() / ".local/share/jmorais-local-pilot"


def tuss_index():
    from jmoraIs.reference.tuss import TussIndex
    path = STATE / "reference/tuss.sqlite"
    return TussIndex(path) if path.exists() else None


def catalog():
    from jmoraIs.application.surgical_catalog import CatalogStore, starter_templates
    store = CatalogStore(STATE / "catalog/procedures.json")
    store.seed(starter_templates(), tuss_index())
    return store


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8770)
    args = parser.parse_args(argv)
    factory = default_classifier_factory()
    print(f"JMORAIS workbench: http://127.0.0.1:{args.port}/  (IA: {'Claude' if factory else 'não configurada — modo manual'})")
    app = create_app(pubmed=PubMedConnector(), crossref=CrossrefConnector(),
                     resolve_classifier=default_classifier_factory, save_key=save_keychain_api_key,
                     resolve_case_extractor=default_case_extractor_factory, tuss_index=tuss_index(), catalog=catalog(),
                     resolve_question_translator=default_question_translator_factory,
                     resolve_report_writer=default_report_writer_factory)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning",
                server_header=False, access_log=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
