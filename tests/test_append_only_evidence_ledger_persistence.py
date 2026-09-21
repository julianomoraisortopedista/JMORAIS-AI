from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from jmoraIs.db import AppendOnlyMutationError, Base, LedgerClaimRecord


def test_orm_rejects_update_and_delete_for_ledger_records():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with Session(engine) as session:
        record = LedgerClaimRecord(claim_id="c1", claim_text="immutable", claim_hash="a" * 64, created_at=created)
        session.add(record)
        session.commit()
        record.claim_text = "tampered"
        with pytest.raises(AppendOnlyMutationError, match="UPDATE"):
            session.commit()
        session.rollback()
        session.delete(record)
        with pytest.raises(AppendOnlyMutationError, match="DELETE"):
            session.commit()
