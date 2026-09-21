from __future__ import annotations

from .tenant_database import create_tenant_runtime_engine


class SecretBackedDatabaseEngine:
    """Resolves credentials only inside infrastructure and supports controlled pool rotation."""
    def __init__(self, secrets, credential_reference, *, runtime_role: str, actor_id="homologation-api",
                 engine_options=None):
        self._secrets,self._reference,self._runtime_role,self._actor=secrets,credential_reference,runtime_role,actor_id
        self._engine=None; self._engine_options = dict(engine_options or {})
    @property
    def engine(self):
        if self._engine is None: self.refresh()
        return self._engine
    def refresh(self):
        replacement=self._secrets.use_secret(self._reference,actor_id=self._actor,
            consumer=lambda value:create_tenant_runtime_engine(value.decode("utf-8"),runtime_role=self._runtime_role,
                **self._engine_options))
        previous,self._engine=self._engine,replacement
        if previous is not None: previous.dispose()
        return replacement
    def close(self):
        if self._engine is not None:
            self._engine.dispose(); self._engine=None
