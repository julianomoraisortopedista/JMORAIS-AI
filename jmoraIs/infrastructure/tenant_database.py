from __future__ import annotations

import re

from sqlalchemy import create_engine, event

from jmoraIs.tenancy.context import current_tenant_context
from jmoraIs.tenancy.domain import MissingTenantContext


_ROLE = re.compile(r"^[a-z][a-z0-9_]{2,62}$")


def create_tenant_runtime_engine(database_url: str, *, runtime_role: str, pool_size: int = 10,
        max_overflow: int = 5, connect_timeout: int = 10, statement_timeout_ms: int = 30_000,
        lock_timeout_ms: int = 5_000, idle_transaction_timeout_ms: int = 30_000,
        application_name: str = "jmorais-api-runtime", require_tls: bool = False):
    if not _ROLE.fullmatch(runtime_role):
        raise ValueError("runtime database role is invalid")
    if min(pool_size, connect_timeout, statement_timeout_ms, lock_timeout_ms,
           idle_transaction_timeout_ms) < 1 or max_overflow < 0:
        raise ValueError("bounded database runtime policy is required")
    options = (f"-c statement_timeout={statement_timeout_ms} "
               f"-c lock_timeout={lock_timeout_ms} "
               f"-c idle_in_transaction_session_timeout={idle_transaction_timeout_ms}")
    connect_args = {"connect_timeout": connect_timeout, "application_name": application_name,
                    "options": options}
    if require_tls: connect_args["sslmode"] = "require"
    engine = create_engine(database_url, future=True, pool_pre_ping=True, pool_size=pool_size,
                           max_overflow=max_overflow, pool_timeout=connect_timeout,
                           connect_args=connect_args)

    @event.listens_for(engine, "begin")
    def _bind_tenant(connection):
        connection.exec_driver_sql(f'SET LOCAL ROLE "{runtime_role}"')
        try: tenant_id = current_tenant_context().tenant_id
        except MissingTenantContext: tenant_id = ""
        connection.exec_driver_sql("SELECT set_config('jmorais.tenant_id', %s, true)", (tenant_id,))

    return engine
