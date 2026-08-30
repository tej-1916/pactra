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
    """FastAPI dependency: one session per request. The HANDLER owns the commit.

    WHY THIS DOES NOT COMMIT
    ------------------------
    It used to. The exit code of a dependency with ``yield`` runs when FastAPI
    closes the request's ``AsyncExitStack``, and that happens AFTER
    ``await response(scope, receive, send)`` — after the bytes are already on
    their way to the caller. Committing there means a client can observe a 201
    describing a row that is not yet durable, and a read issued immediately
    afterwards races the commit. Measured against a real server, a create
    followed by an immediate read of the same mission returned 404 for roughly
    83-92% of attempts.

    So the transaction boundary moved out to the route handler, which is the
    outermost edge of the HTTP unit of work and the only place that can commit
    BEFORE the response is constructed. This also matches how the rest of the
    repository already works: the payment worker, the attack lab, and the risk
    harness each commit their own unit of work explicitly.

    WHY THE SUCCESS PATH ROLLS BACK
    -------------------------------
    Anything a handler did not explicitly commit is discarded. Committing here
    as a safety net would silently reintroduce the very ordering this function
    exists to prevent, and would do it for exactly the routes nobody remembered
    to look at. Discarding instead makes a forgotten commit fail loudly and
    immediately — the mutation simply does not happen — rather than working in
    tests and racing in production. Every read-only route is unaffected: a
    rollback on a session that wrote nothing is a no-op.
    """
    maker = get_sessionmaker()
    async with maker() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        else:
            await session.rollback()
