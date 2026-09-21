from __future__ import annotations

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import Engine

from jmoraIs.api.security import ReadinessCheck, ReadinessReport


class PostgreSQLApiReadinessAdapter:
    def __init__(self, engine: Engine, *, alembic_config: str = "alembic.ini",
                 critical_checks: tuple[ReadinessCheck, ...] = ()) -> None:
        self._engine = engine; self._alembic_config = alembic_config; self._critical = critical_checks

    def check(self) -> ReadinessReport:
        try:
            with self._engine.connect() as connection:
                connection.execute(text("SELECT 1"))
                current = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            head = ScriptDirectory.from_config(Config(self._alembic_config)).get_current_head()
            database = ReadinessCheck("postgresql", True, "AVAILABLE")
            migration = ReadinessCheck("migrations", current == head,
                                       "CURRENT" if current == head else "OUTDATED")
        except Exception:
            database = ReadinessCheck("postgresql", False, "UNAVAILABLE")
            migration = ReadinessCheck("migrations", False, "UNKNOWN")
        return ReadinessReport((database, migration) + self._critical)
