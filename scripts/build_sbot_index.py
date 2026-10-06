#!/usr/bin/env python3
"""Build the local SBOT coding-manual index from the PDF the SBOT publishes.

Source: https://defesa.sbot.org.br/assets/file/Manual-SBOT-27-11-25.pdf (or a newer edition).
Output: ~/.local/share/jmorais-local-pilot/reference/sbot.json (stays on this computer).
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from jmoraIs.reference.sbot import build_index

OUTPUT = Path.home() / ".local/share/jmorais-local-pilot/reference/sbot.json"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pdf", type=Path, help="SBOT coding manual PDF")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    counts = build_index(args.pdf, args.output)
    print(f"SBOT index ready at {args.output}: {counts['entries']} procedures, "
          f"{counts['with_codes']} with codes, {counts['with_opme']} with OPME")
    return 0


if __name__ == "__main__":
    sys.exit(main())
