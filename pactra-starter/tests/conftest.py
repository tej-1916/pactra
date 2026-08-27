"""Test fixtures: in-memory async SQLite engine + session, and a TestClient
wired to that session so the API integration test hits the same DB."""

from __future__ import annotations

import pytest_asyncio
from apps.api.db import models  # noqa: F401  (register metadata)
from apps.api.db.base import Base
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def sessionmaker(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def session(sessionmaker) -> AsyncSession:
    async with sessionmaker() as s:
        yield s


@pytest_asyncio.fixture
async def client(sessionmaker):
    from apps.api.db.session import get_session
    from apps.api.pactra.main import app

    async def _override():
        async with sessionmaker() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    app.dependency_overrides[get_session] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


def make_constraints(**overrides):
    from packages.schemas.domain import MissionConstraints

    base = dict(
        category="wireless_earbuds",
        soft_budget_inr=4000,
        hard_limit_inr=4500,
        min_rating=4.2,
        currency="INR",
    )
    base.update(overrides)
    return MissionConstraints(**base)


def collect_quotes(constraints, quantity=1, merchants=None, registry=None):
    """Run merchants through the real transport so every quote carries the
    identity the transport authenticated — the same path the orchestrator uses."""
    from services.agent_orchestrator.merchants.mock_merchants import default_merchants
    from services.agent_orchestrator.merchants.transport import MerchantTransport

    agents = default_merchants() if merchants is None else merchants
    return MerchantTransport(registry).collect(agents, constraints, quantity)
