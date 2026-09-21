#!/usr/bin/env python3
"""Generate or verify the canonical, reference-only RC release manifest."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import subprocess

from jmoraIs import __version__
from jmoraIs.infrastructure.production_runtime import CURRENT_SCHEMA_REVISION
from jmoraIs.infrastructure.release_security import (
    ArtifactDigest, ReleaseIdentity, ReleaseManifest, ReleaseVerifier, SignatureReference,
    load_manifest, sha256_file,
)


def git_revision() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()


def generate(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    paths = {name: Path(value) for name, value in (
        ("dependency_lock", args.dependency_lock), ("container", args.container),
        ("sbom", args.sbom), ("vulnerability", args.vulnerability), ("sast", args.sast),
        ("secret_scan", args.secret_scan), ("provenance", args.provenance),
    )}
    artifacts = {name: ArtifactDigest(str(path), sha256_file(root / path)) for name, path in paths.items()}
    revision = git_revision()
    built_at = args.timestamp or datetime.now(timezone.utc).isoformat()
    identity = ReleaseIdentity(__version__, revision, args.build_id,
        platform.python_version(), CURRENT_SCHEMA_REVISION, artifacts["dependency_lock"].digest,
        artifacts["container"].digest, built_at)
    coverage = args.coverage
    if args.coverage_json:
        coverage = float(json.loads((root / args.coverage_json).read_text(encoding="utf-8"))["totals"]["percent_covered"])
    test_summary = args.test_summary
    if args.test_summary_file:
        test_summary = (root / args.test_summary_file).read_text(encoding="utf-8").strip().splitlines()[-1]
    if coverage is None or not test_summary:
        raise ValueError("measured coverage and test summary are required")
    manifest = ReleaseManifest(1, identity, artifacts,
        SignatureReference("INSTITUTIONAL_SIGNING_PENDING", "NONE", "UNASSIGNED", None, None),
        test_summary, coverage, args.complete_case, args.replay)
    output = root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(output)
    return 0


def verify(args: argparse.Namespace) -> int:
    manifest = load_manifest(args.manifest)
    ReleaseVerifier(allow_institutional_signing_pending=args.allow_pending).verify(
        manifest, args.root, expected_source_revision=git_revision(),
        expected_alembic_revision=CURRENT_SCHEMA_REVISION, expected_version=__version__)
    print("release manifest verification: PASS")
    return 0


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    sub = value.add_subparsers(dest="command", required=True)
    create = sub.add_parser("generate")
    create.add_argument("--root", default="."); create.add_argument("--output", required=True)
    create.add_argument("--build-id", required=True); create.add_argument("--timestamp")
    create.add_argument("--dependency-lock", default="requirements-production.lock")
    for name in ("container", "sbom", "vulnerability", "sast", "secret-scan", "provenance"):
        create.add_argument("--" + name, required=True)
    create.add_argument("--test-summary"); create.add_argument("--test-summary-file")
    create.add_argument("--coverage", type=float); create.add_argument("--coverage-json")
    create.add_argument("--complete-case", required=True); create.add_argument("--replay", required=True)
    create.set_defaults(handler=generate)
    check = sub.add_parser("verify")
    check.add_argument("--root", default="."); check.add_argument("--manifest", required=True)
    check.add_argument("--allow-pending", action="store_true")
    check.set_defaults(handler=verify)
    return value


if __name__ == "__main__":
    arguments = parser().parse_args()
    raise SystemExit(arguments.handler(arguments))
