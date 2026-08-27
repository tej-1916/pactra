"""PostgreSQL test support.

Phase 4 stops treating SQLite as sufficient. SQLite serializes writers with a
whole-database lock, which means a "concurrency" test there proves the code is
safe under a regime that removes most of the concurrency. PostgreSQL uses
row-level locks and MVCC, so two sessions genuinely interleave — and that is the
regime the payment executor will actually run in.

The critical integration tests therefore run against a real PostgreSQL server.
Fast SQLite tests are kept where the property under test is not about
concurrency, because a 4-second suite is worth having.

If the server is unreachable the tests SKIP with an explicit message. They never
silently pass: a concurrency guarantee that was not exercised must not look like
one that was.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

#: Overridable so this runs against any PostgreSQL, not just the compose one.
DEFAULT_URL = "postgresql+asyncpg://pactra:pactra@localhost:5432/pactra_test"
POSTGRES_URL = os.environ.get("PACTRA_TEST_DATABASE_URL", DEFAULT_URL)

SKIP_REASON = (
    "PostgreSQL is required for Phase 4 integration tests. Start it with "
    "`docker compose -f infra/docker-compose.yml up -d`, or point "
    "PACTRA_TEST_DATABASE_URL at a server. "
    f"Tried: {POSTGRES_URL.rsplit('@', 1)[-1]}"
)

#: Tables truncated between tests, ordered so CASCADE has nothing to chase.
_TABLES = (
    "webhook_events",
    "outbox_events",
    "payment_intents",
    "authorizations",
    "audit_events",
    "policy_decisions",
    "offers",
    "mission_constraints",
    "missions",
)


def make_engine(url: str = POSTGRES_URL):
    """An engine whose sessions hold SEPARATE connections.

    ``NullPool`` is not an optimisation choice here — it is what makes the
    concurrency tests meaningful. With a pooled engine two "concurrent"
    sessions can be handed the same connection, and a race that cannot happen
    is not a race that was tested.
    """
    return create_async_engine(url, future=True, poolclass=NullPool)


async def ensure_database() -> bool:
    """Create the test database if needed. False if the server is unreachable."""
    admin_url = POSTGRES_URL.rsplit("/", 1)[0] + "/postgres"
    target = POSTGRES_URL.rsplit("/", 1)[-1]

    engine = create_async_engine(
        admin_url, future=True, poolclass=NullPool, isolation_level="AUTOCOMMIT"
    )
    try:
        async with engine.connect() as conn:
            from sqlalchemy import text

            exists = await conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": target}
            )
            if not exists:
                await conn.execute(text(f'CREATE DATABASE "{target}"'))
        return True
    except Exception:
        return False
    finally:
        await engine.dispose()


async def truncate_all(engine) -> None:
    """Reset state between tests.

    TRUNCATE rather than DROP/CREATE: the schema is created once per session, so
    each test pays for row removal instead of DDL, and the tables under test are
    exactly the ones the migrations produce.
    """
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE"))


def sessionmaker_for(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


#: Applied to every test in this suite that needs a real PostgreSQL server.
postgres = pytest.mark.postgres
