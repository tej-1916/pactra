"""Alembic environment.

Runs migrations with a *sync* engine derived from the configured async URL
(async drivers are swapped for their sync equivalents), so a single migration
set applies to both PostgreSQL and SQLite.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from apps.api.db import models  # noqa: F401  (imported for metadata registration)
from apps.api.db.base import Base
from apps.api.pactra.config import get_settings
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _sync_url() -> str:
    """The configured async URL, rewritten to its synchronous driver.

    Alembic runs migrations synchronously, so the async driver has to be
    swapped out. PostgreSQL maps to psycopg 3 (``+psycopg``) rather than
    psycopg2: psycopg2 publishes no wheel for the Python version this project
    targets, and psycopg 3 is the maintained successor. SQLite's ``+aiosqlite``
    drops to the stdlib driver.
    """
    url = get_settings().database_url
    return url.replace("+asyncpg", "+psycopg").replace("+aiosqlite", "")


def run_migrations_offline() -> None:
    context.configure(
        url=_sync_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = _sync_url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # needed for SQLite ALTERs
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
