"""Async engine/session management."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from apps.api.pactra.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def configure_sqlite_transactions(engine: AsyncEngine) -> AsyncEngine:
    """Give SQLite real transactions and working SAVEPOINTs.

    WHY THIS IS NOT OPTIONAL. Python's sqlite3 driver manages transactions
    itself: it opens one implicitly before certain statements and commits it
    behind your back before others. The consequences are severe for this
    codebase specifically:

    * ``ROLLBACK`` silently does nothing, because no transaction was open. The
      Phase 4 atomicity guarantee — "if the transaction rolls back, the
      authorization consumption rolls back too" — is untestable and untrue on a
      default SQLite engine.
    * ``SAVEPOINT`` behaves the same way, so ``session.begin_nested()`` does not
      isolate the block it wraps. Payment intent creation relies on a savepoint
      to undo a losing request's authorization consume.

    The two listeners below are SQLAlchemy's documented remedy: disable the
    driver's implicit transaction handling, then emit ``BEGIN`` explicitly so a
    transaction genuinely exists. PostgreSQL needs none of this — it is a defect
    of the sqlite3 driver, not of the database — so the engine is returned
    unmodified for every other dialect.
    """
    if engine.dialect.name != "sqlite":
        return engine

    sync_engine = engine.sync_engine

    @event.listens_for(sync_engine, "connect")
    def _disable_implicit_transactions(dbapi_connection, _record):  # type: ignore[misc]
        dbapi_connection.isolation_level = None

    @event.listens_for(sync_engine, "begin")
    def _emit_explicit_begin(connection):  # type: ignore[misc]
        connection.exec_driver_sql("BEGIN")

    return engine


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = configure_sqlite_transactions(
            create_async_engine(get_settings().database_url, future=True)
        )
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request, committed on success."""
    maker = get_sessionmaker()
    async with maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
