#!/usr/bin/env python3
"""Restore a logical backup and require an independently VALID replay."""
import json
import os
import subprocess
import tempfile
import hashlib
from pathlib import Path
from sqlalchemy import create_engine, text
from jmoraIs.infrastructure.cryptographic_replay import PostgreSQLCryptographicReplayEngine, ReplayIntegrityStatus


def validate(url: str) -> dict[str, object]:
    engine = create_engine(url)
    tables=("canonical_ledger_events","evidence_package_catalog","evidence_package_versions",
      "governed_evidence_versions","governed_evidence_lifecycle_events","governed_clinical_audit_events",
      "clinical_conflict_adjudication_events","reviewer_identities")
    def snapshot():
        with engine.connect() as connection:
            counts={table:connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() for table in tables}
        encoded=json.dumps(counts,sort_keys=True).encode()
        return counts,hashlib.sha256(encoded).hexdigest()
    before_counts,before_state_hash=snapshot()
    before = PostgreSQLCryptographicReplayEngine(engine).replay_all()
    if before.overall_decision != ReplayIntegrityStatus.VALID:
        raise RuntimeError("source replay is not VALID")
    cli_url = url.replace("postgresql+psycopg://", "postgresql://", 1)
    with tempfile.TemporaryDirectory(prefix="jmorais-backup-") as directory:
        dump = Path(directory) / "platform.sql"
        subprocess.run(["pg_dump", "--format=plain", "--no-owner", "--file", str(dump), cli_url], check=True)
        # PostgreSQL 17 clients emit this setting, which PostgreSQL 16 does not know.
        dump.write_text(dump.read_text().replace("SET transaction_timeout = 0;\n", ""))
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
        subprocess.run(["psql", "--set", "ON_ERROR_STOP=1", "--dbname", cli_url,
                        "--file", str(dump)], check=True, stdout=subprocess.DEVNULL)
    after = PostgreSQLCryptographicReplayEngine(engine).replay_all()
    if after.overall_decision != ReplayIntegrityStatus.VALID:
        raise RuntimeError("restored replay is not VALID")
    if (before.verified_events, len(before.streams)) != (after.verified_events, len(after.streams)):
        raise RuntimeError("restored stream inventory differs")
    after_counts,after_state_hash=snapshot()
    if before_counts != after_counts or before_state_hash != after_state_hash:
        raise RuntimeError("restored reconstructed state differs")
    return {"backup": "VALID", "restore": "VALID", "replay": "VALID",
            "verified_events": after.verified_events, "streams": len(after.streams),
            "state_equivalent": True,"state_hash":after_state_hash,"table_counts":after_counts}


if __name__ == "__main__":
    result=validate(os.environ["JMORAIS_TEST_POSTGRES_URL"])
    if os.getenv("JMORAIS_REPLAY_REPORT"):
        report_path=Path(os.environ["JMORAIS_REPLAY_REPORT"]);report_path.parent.mkdir(parents=True,exist_ok=True)
        report_path.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print(json.dumps(result, sort_keys=True))
