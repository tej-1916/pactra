"""SUCCESS_RESPONSE_IMPLIES_DURABLE_COMMIT.

WHY THIS FILE NEEDS A REAL SERVER
---------------------------------
The rest of the API suite drives the app through ``httpx.ASGITransport`` and
overrides ``get_session`` with a test-local copy. Both choices hide the defect
this file exists to catch:

* ``ASGITransport`` closes FastAPI's dependency ``AsyncExitStack`` before
  ``handle_async_request`` returns, so a finalizer that commits AFTER the
  response was sent still appears to commit before the next call.
* the override means the real dependency is never exercised at all.

So a test written in that style can pass while every real client races the
commit. These tests therefore run a genuine uvicorn server over a real TCP
socket, against the real ``get_session``, and assert only what a caller can
observe: a success response for a mutation must mean the mutation is already
durable. No sleep and no retry — either the invariant holds or it does not.
"""

from __future__ import annotations

import asyncio
import os
import socket
import time

import httpx
import pytest

pytestmark = pytest.mark.postgres

#: Enough attempts that the pre-fix race (measured at ~83-92% failure with no
#: delay) cannot plausibly pass by luck, while keeping the suite quick.
ATTEMPTS = 40


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.fixture
def live_server():
    """A real uvicorn server on a real port, using the real session dependency.

    The server runs in its own thread with its own event loop. That is not
    incidental: this project sets ``asyncio_default_fixture_loop_scope =
    "session"``, so a server started on the fixture's loop would never be
    driven while the test's loop awaited it, and every request would time out.
    Giving the server its own loop also means the app builds its own engine
    there, which is what a deployed process actually does.
    """
    import threading

    import uvicorn
    from sqlalchemy.ext.asyncio import create_async_engine
    from tests.pg import POSTGRES_URL, ensure_database

    async def _prepare() -> bool:
        if not await ensure_database():
            return False
        from apps.api.db.base import Base

        engine = create_async_engine(POSTGRES_URL, future=True)
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        finally:
            await engine.dispose()
        return True

    if not asyncio.run(_prepare()):
        pytest.skip("PostgreSQL is required for response/commit ordering tests")

    from apps.api.db import session as session_module
    from apps.api.pactra.config import get_settings

    previous = (
        os.environ.get("DATABASE_URL"),
        session_module._engine,
        session_module._sessionmaker,
    )
    os.environ["DATABASE_URL"] = POSTGRES_URL
    get_settings.cache_clear()
    # Force the server thread to build its own engine on its own loop.
    session_module._engine = None
    session_module._sessionmaker = None

    from apps.api.pactra.main import app

    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    # The server owns the process signal handlers by default; installing them
    # off the main thread raises, so they are disabled explicitly.
    server.install_signal_handlers = lambda: None  # type: ignore[method-assign]
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.monotonic() + 30
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    if not server.started:  # pragma: no cover - the server failed to come up
        server.should_exit = True
        thread.join(timeout=10)
        pytest.fail("uvicorn did not start")

    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=15)
        url, engine, maker = previous
        if url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = url
        session_module._engine = engine
        session_module._sessionmaker = maker
        get_settings.cache_clear()


def _mission_body() -> dict:
    return {
        "raw_query": "wireless earbuds",
        "quantity": 1,
        "constraints": {
            "category": "wireless_earbuds",
            "soft_budget_inr": 4000,
            "hard_limit_inr": 9000,
            "min_rating": 3.5,
            "currency": "INR",
        },
    }


async def test_created_mission_is_readable_immediately(live_server):
    """POST /missions returning 201 must mean the mission is already durable.

    This is the exact sequence a browser performs when the console navigates to
    the detail page it just created, and the sequence that returned 404 for
    ~83-92% of attempts before the fix.
    """
    missing: list[str] = []
    async with httpx.AsyncClient(base_url=live_server, timeout=30.0) as client:
        for _ in range(ATTEMPTS):
            created = await client.post("/api/v1/missions", json=_mission_body())
            assert created.status_code == 201, created.text
            mission_id = created.json()["id"]

            # No sleep and no retry, deliberately.
            read = await client.get(f"/api/v1/missions/{mission_id}")
            if read.status_code != 200:
                missing.append(f"{mission_id}: HTTP {read.status_code}")

    assert not missing, (
        f"{len(missing)}/{ATTEMPTS} missions were not durable when their own 201 "
        f"was observed: {missing[:5]}"
    )


async def test_recorded_risk_assessment_is_readable_immediately(live_server):
    """The same invariant on a second, independent mutation endpoint.

    POST /risk/assess appends a RISK_ASSESSED audit event. A 201 that does not
    yet imply a readable event is the same defect wearing a different route, so
    it is proven separately rather than assumed to follow.
    """
    missing: list[str] = []
    async with httpx.AsyncClient(base_url=live_server, timeout=30.0) as client:
        for _ in range(ATTEMPTS):
            created = await client.post("/api/v1/missions", json=_mission_body())
            assert created.status_code == 201, created.text
            mission_id = created.json()["id"]

            recorded = await client.post(f"/api/v1/missions/{mission_id}/risk/assess")
            assert recorded.status_code == 201, recorded.text

            events = await client.get(f"/api/v1/missions/{mission_id}/events")
            if events.status_code != 200:
                missing.append(f"{mission_id}: events HTTP {events.status_code}")
                continue
            if not any(e["event_type"] == "RISK_ASSESSED" for e in events.json()):
                missing.append(f"{mission_id}: RISK_ASSESSED not durable")

    assert not missing, (
        f"{len(missing)}/{ATTEMPTS} risk assessments were not durable when their "
        f"own 201 was observed: {missing[:5]}"
    )


async def test_concurrent_creates_are_each_durable_on_their_own_response(live_server):
    """Independent concurrent missions must each be readable on their own 201.

    Concurrency is the regime where a commit deferred past the response is most
    likely to be masked by another request's commit happening to flush first.
    """
    async with httpx.AsyncClient(base_url=live_server, timeout=30.0) as client:

        async def create_then_read() -> int:
            created = await client.post("/api/v1/missions", json=_mission_body())
            assert created.status_code == 201, created.text
            read = await client.get(f"/api/v1/missions/{created.json()['id']}")
            return read.status_code

        statuses = await asyncio.gather(*(create_then_read() for _ in range(20)))

    assert all(status == 200 for status in statuses), (
        f"{sum(1 for s in statuses if s != 200)}/20 concurrent creates were not "
        f"durable on their own response: {statuses}"
    )
