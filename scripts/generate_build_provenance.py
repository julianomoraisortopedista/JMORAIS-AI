#!/usr/bin/env python3
"""Generate a minimal SLSA v1-compatible provenance statement without secrets."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

from jmoraIs.infrastructure.release_security import sha256_file


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", required=True); parser.add_argument("--lock", required=True)
    parser.add_argument("--sbom", required=True); parser.add_argument("--output", required=True)
    parser.add_argument("--build-id", required=True); parser.add_argument("--builder-id", required=True)
    parser.add_argument("--timestamp")
    args = parser.parse_args()
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    timestamp = args.timestamp or datetime.now(timezone.utc).isoformat()
    statement = {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [{"name": Path(args.artifact).name, "digest": {"sha256": sha256_file(args.artifact)[7:]}}],
        "predicateType": "https://slsa.dev/provenance/v1",
        "predicate": {
            "buildDefinition": {
                "buildType": "https://jmorais.ai/build/python-container/v1",
                "externalParameters": {"build_id": args.build_id},
                "internalParameters": {},
                "resolvedDependencies": [
                    {"uri": "git+repository", "digest": {"gitCommit": revision}},
                    {"uri": Path(args.lock).name, "digest": {"sha256": sha256_file(args.lock)[7:]}},
                    {"uri": Path(args.sbom).name, "digest": {"sha256": sha256_file(args.sbom)[7:]}},
                ],
            },
            "runDetails": {
                "builder": {"id": args.builder_id},
                "metadata": {"invocationId": args.build_id, "startedOn": timestamp, "finishedOn": timestamp},
                "byproducts": [],
            },
        },
    }
    Path(args.output).write_text(json.dumps(statement, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__": raise SystemExit(main())
