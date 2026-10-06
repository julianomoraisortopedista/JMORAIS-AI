#!/usr/bin/env python3
"""Download the latest official ANS TUSS package and build the local search index.

Source: https://www.ans.gov.br/arquivos/extras/tiss/Padrao_TISS_Representacao_de_Conceitos_em_Saude_YYYYMM.zip
Output: ~/.local/share/jmorais-local-pilot/reference/tuss.sqlite (public reference data, no secrets).
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import sys
import tempfile

import requests

from jmoraIs.reference.tuss import build_index

BASE = "https://www.ans.gov.br/arquivos/extras/tiss/Padrao_TISS_Representacao_de_Conceitos_em_Saude_{}.zip"
OUTPUT = Path.home() / ".local/share/jmorais-local-pilot/reference/tuss.sqlite"


def latest_version(today: date, months: int = 24) -> str:
    year, month = today.year, today.month
    for _ in range(months):
        version = f"{year}{month:02d}"
        response = requests.head(BASE.format(version), timeout=30, allow_redirects=True, headers={"User-Agent": "jmorais"})
        if response.status_code == 200:
            return version
        year, month = (year, month - 1) if month > 1 else (year - 1, 12)
    raise SystemExit("No official TUSS package found in the last 24 months.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--zip", type=Path, help="Use an already downloaded official package")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    args.output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if args.zip:
        counts = build_index(args.zip, args.output)
    else:
        version = latest_version(date.today())
        print(f"Downloading official TUSS package {version} (~400 MB)…")
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / f"Padrao_TISS_{version}.zip"
            with requests.get(BASE.format(version), stream=True, timeout=600, headers={"User-Agent": "jmorais"}) as r:
                r.raise_for_status()
                with open(target, "wb") as handle:
                    for chunk in r.iter_content(1 << 20):
                        handle.write(chunk)
            counts = build_index(target, args.output)
    print(f"TUSS index ready at {args.output}: {counts['procedures']} procedures, {counts['materials']} materials/OPME")
    return 0


if __name__ == "__main__":
    sys.exit(main())
