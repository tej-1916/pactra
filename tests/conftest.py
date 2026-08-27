"""Test fixtures.

Three engines are provided deliberately:

* ``engine`` / ``session`` — in-memory SQLite for the bulk of the suite.
* ``client`` — a TestClient wired to that same in-memory database.
* ``concurrent_sessionmaker`` — a FILE-BACKED SQLite engine with ``NullPool``, so
  two sessions hold genuinely separate connections. The in-memory engine cannot
  serve that purpose: SQLAlchemy backs a ``:memory:`` database with a single
  shared connection, so two "concurrent" sessions would be the same connection
  and no race could occur at all.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from apps.api.db import models  # noqa: F401  (register metadata)
from apps.api.db.base import Base
from apps.api.db.session import configure_sqlite_transactions
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool


@pytest_asyncio.fixture
async def engine():
    # configure_sqlite_transactions is not a test nicety: without it the sqlite3
    # driver manages transactions itself, ROLLBACK is a no-op, and SAVEPOINT
    # does not isolate. Every rollback/atomicity assertion below would pass
    # vacuously. See apps/api/db/session.py for the full explanation.
    eng = configure_sqlite_transactions(
        create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    )
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


# --------------------------------------------------------------------------- #
# Phase 3 — a second engine that supports genuine connection-level concurrency
# --------------------------------------------------------------------------- #
@pytest_asyncio.fixture
async def concurrent_sessionmaker(tmp_path):
    """A file-backed SQLite engine whose sessions get separate connections.

    ``NullPool`` means every session checks out its own connection, so two
    sessions can both read ACTIVE before either writes — the exact interleaving
    a double-consume race requires.
    """
    url = f"sqlite+aiosqlite:///{tmp_path / 'pactra-concurrency.db'}"
    eng = configure_sqlite_transactions(create_async_engine(url, future=True, poolclass=NullPool))

    # WAL + a busy timeout is the closest SQLite gets to concurrent readers and
    # a writer. It is still NOT PostgreSQL: SQLite locks the whole database for
    # writing, so when two sessions each hold an open transaction, the loser is
    # refused by SQLite's own concurrency control (OperationalError) rather than
    # by the conditional UPDATE matching zero rows. Exactly one writer still
    # wins — the safety invariant holds — but the REASON differs, which is
    # precisely why Phase 4 proves the payment concurrency properties against a
    # real PostgreSQL server (tests/test_postgres_concurrency.py).
    @event.listens_for(eng.sync_engine, "connect")
    def _concurrency_pragmas(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(eng, expire_on_commit=False)
    await eng.dispose()


# --------------------------------------------------------------------------- #
# Phase 3 — transaction / offer builders
# --------------------------------------------------------------------------- #
#: A nonce-shaped constant. Real nonces come from `generate_nonce()`; tests that
#: are not about nonce generation use a fixed one so digests are reproducible.
FIXED_NONCE = "a" * 64

FIXED_EXPIRY = datetime(2030, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def approved_transaction(**overrides):
    """The canonical 'approved' transaction used across the Phase 3 tests."""
    from packages.schemas.transaction import BoundTransaction

    base = dict(
        merchant_id="merchant_a",
        product_id="P1",
        quantity=1,
        amount_inr=3799,
        currency="INR",
        policy_version="policy-v1",
        offer_version="offer-v1",
        expires_at=FIXED_EXPIRY,
        nonce=FIXED_NONCE,
    )
    base.update(overrides)
    return BoundTransaction(**base)


#: One or more different-but-valid values for each bound field. Used to prove
#: exhaustively that mutating ANY bound field breaks the binding. A field with
#: no entry here fails `test_every_bound_field_has_a_mutator`, so adding a bound
#: field without proving it is protected is not possible.
FIELD_MUTATIONS: dict[str, list] = {
    "merchant_id": ["merchant_b", "attacker-merchant"],
    "product_id": ["P2", "aur-eb-02"],
    "quantity": [2, 5],
    "amount_inr": [4399, 3798, 1],
    "currency": ["USD", "EUR"],
    "policy_version": ["policy-v2", "policy-v0"],
    "offer_version": ["offer-v2", "deadbeef"],
    "expires_at": [FIXED_EXPIRY + timedelta(hours=1), FIXED_EXPIRY + timedelta(days=365)],
    "nonce": ["b" * 64, "c" * 64],
}


def mutations_for(transaction, field: str):
    """Every single-field mutation of `transaction` for `field`."""
    assert field in FIELD_MUTATIONS, f"no mutator declared for bound field '{field}'"
    return [
        transaction.model_copy(update={field: value})
        for value in FIELD_MUTATIONS[field]
        if value != getattr(transaction, field)
    ]


# --------------------------------------------------------------------------- #
# Phase 3 — provenance-coupled offer fixtures
# --------------------------------------------------------------------------- #
def _ingest(merchant_registration: str, claimed_id: str, **payload):
    """Build a ProvenancedOffer through the real ingress, so identity comes from
    the transport exactly as it does in production."""
    from packages.schemas.domain import RawMerchantOffer
    from packages.schemas.merchant import MerchantAuthMethod, MerchantIdentity
    from services.security_kernel.ingress import ingest_merchant_offer
    from services.security_kernel.merchant_registry import default_merchant_registry

    base = dict(
        merchant_id=claimed_id,
        product_id="P1",
        title="Test Earbuds",
        price=3799,
        currency="INR",
        rating=4.6,
        in_stock=True,
        offered_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
    )
    base.update(payload)
    identity = MerchantIdentity(
        merchant_id=merchant_registration,
        auth_method=MerchantAuthMethod.IN_PROCESS_ADAPTER,
        channel="in-process",
    )
    context = default_merchant_registry().context_for(identity)
    return ingest_merchant_offer(RawMerchantOffer(**base), context)


@pytest.fixture
def valid_offer():
    """An honest offer from merchant_a."""
    return _ingest("merchant_a", "merchant_a")


@pytest.fixture
def second_offer():
    """A different honest offer, for 'wrong offer' checks."""
    return _ingest("merchant_a", "merchant_a", product_id="P2", price=2999)


@pytest.fixture
def spoofed_offer():
    """Transport-authenticated as `evil`, payload claims to be `merchant_a`."""
    return _ingest("evil", "merchant_a")


# --------------------------------------------------------------------------- #
# Phase 3 — mission helper (authorizations are FK-bound to a mission)
# --------------------------------------------------------------------------- #
async def make_mission(session, state: str = "POLICY_CHECKED"):
    from apps.api.db.models import Mission

    mission = Mission(id=uuid.uuid4(), quantity=1, state=state)
    session.add(mission)
    await session.flush()
    return mission


# --------------------------------------------------------------------------- #
# Phase 4 — PostgreSQL fixtures
# --------------------------------------------------------------------------- #
@pytest_asyncio.fixture(scope="session")
async def pg_engine():
    """One engine and one schema for the whole PostgreSQL suite.

    Skips — loudly, with instructions — when no server is reachable. A
    concurrency guarantee that was not exercised must never be reported as one
    that was, so this never degrades to SQLite behind the caller's back.
    """
    from tests.pg import SKIP_REASON, ensure_database, make_engine

    if not await ensure_database():
        pytest.skip(SKIP_REASON, allow_module_level=True)

    engine = make_engine()
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception:  # pragma: no cover - server vanished between calls
        await engine.dispose()
        pytest.skip(SKIP_REASON, allow_module_level=True)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def pg_sessionmaker(pg_engine):
    """Per-test clean database, with connection-level concurrency available."""
    from tests.pg import sessionmaker_for, truncate_all

    await truncate_all(pg_engine)
    return sessionmaker_for(pg_engine)


@pytest_asyncio.fixture
async def pg_session(pg_sessionmaker):
    async with pg_sessionmaker() as s:
        yield s


# --------------------------------------------------------------------------- #
# Phase 4 — payment fixtures
# --------------------------------------------------------------------------- #
async def authorized_mission(session, *, amount_inr: int = 3799, quantity: int = 1, **overrides):
    """A mission in AUTHORIZED with an ACTIVE authorization bound to a transaction.

    This is the precondition every payment test starts from, built through the
    REAL kernel path — issue then activate — so the authorization a payment
    consumes is indistinguishable from one a live mission produced.

    Returns (mission, authorization_row, bound_transaction).
    """
    from packages.schemas.capability import security_kernel_capabilities
    from services.security_kernel.authorization import (
        activate_authorization,
        generate_nonce,
        issue_authorization,
    )

    mission = await make_mission(session, state="POLICY_CHECKED")
    txn = approved_transaction(
        amount_inr=amount_inr,
        quantity=quantity,
        expires_at=FIXED_EXPIRY,
        nonce=generate_nonce(),
        **overrides,
    )
    row = await issue_authorization(
        session,
        capabilities=security_kernel_capabilities(),
        mission_id=mission.id,
        transaction=txn,
    )
    await activate_authorization(session, authorization_id=row.authorization_id)
    mission.state = "AUTHORIZED"
    await session.flush()
    return mission, row, txn
