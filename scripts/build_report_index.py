#!/usr/bin/env python3
"""Create a content-addressed index for multiple scanner reports."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from jmoraIs.infrastructure.release_security import sha256_file


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--output", required=True)
    parser.add_argument("--timestamp"); parser.add_argument("reports", nargs="+")
    args = parser.parse_args()
    value = {"schema_version": 1, "generated_at": args.timestamp or datetime.now(timezone.utc).isoformat(),
        "reports": [{"path": item, "digest": sha256_file(item)} for item in sorted(args.reports)]}
    Path(args.output).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__": raise SystemExit(main())
