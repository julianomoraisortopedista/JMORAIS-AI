import os

from alembic import context
from sqlalchemy import engine_from_config, pool

from jmoraIs.infrastructure.postgresql_package_catalog import PackageCatalogBase

config = context.config
runtime_url = os.getenv("JMORAIS_TEST_POSTGRES_URL") or os.getenv("DATABASE_URL")
if runtime_url:
    config.set_main_option("sqlalchemy.url", runtime_url.replace("%", "%%"))
target_metadata = PackageCatalogBase.metadata


def run_migrations_offline():
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(config.get_section(config.config_ini_section), prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_offline() if context.is_offline_mode() else run_migrations_online()
