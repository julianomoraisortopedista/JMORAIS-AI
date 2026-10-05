#!/usr/bin/env python3
"""Start the local physician workbench at http://127.0.0.1:8770 (this computer only)."""
from __future__ import annotations

import argparse

import uvicorn

from jmoraIs.connect.crossref import CrossrefConnector
from jmoraIs.connect.pubmed import PubMedConnector
from jmoraIs.workbench.app import create_app, default_classifier_factory


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8770)
    args = parser.parse_args(argv)
    factory = default_classifier_factory()
    print(f"JMORAIS workbench: http://127.0.0.1:{args.port}/  (IA: {'Claude' if factory else 'não configurada — modo manual'})")
    uvicorn.run(create_app(pubmed=PubMedConnector(), crossref=CrossrefConnector(), classifier_factory=factory), host="127.0.0.1", port=args.port, log_level="warning",
                server_header=False, access_log=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
