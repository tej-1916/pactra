"""The Phase 4 HTTP surface.

These tests are NOT a second copy of the reliability tests. The invariants —
one logical payment per key, no settlement on a mismatch, no regression from a
late webhook — are proven directly against the services, because an HTTP test
only ever proves the route is wired to something. What is proven HERE is what
only the route can get wrong:

* that a request cannot supply the amount, the merchant, or a capability set;
* that no HTTP request reaches a payment provider;
* that an unverified webhook changes nothing and is answered 401;
* that the 201/200 distinction reports the idempotency outcome honestly.
"""

from __future__ import annotations

import json

import pytest
from packages.schemas.domain import MissionState
from packages.schemas.payment import PaymentIntentState, WebhookEventType
from services.payment_executor.providers.fake import webhook_body
from tests.conftest import authorized_mission

pytestmark = pytest.mark.asyncio


@pytest.fixture
def runtime_provider():
    """The process-wide fake the routes resolve, reset between tests.

    ``registry._fake`` is lru_cached on purpose — the fake's payment store IS
    its state — so a test that did not clear it would inherit the previous
    test's payments and prove nothing about its own.
    """
    from services.payment_executor import registry

    registry._fake.cache_clear()
    provider = registry._fake()
    yield provider
    registry._fake.cache_clear()


async def _authorized(sessionmaker):
    async with sessionmaker() as s:
        mission, authorization, _ = await authorized_mission(s)
        await s.commit()
        return mission.id, authorization.authorization_id


# --------------------------------------------------------------------------- #
# 1. Requesting a payment
# --------------------------------------------------------------------------- #
async def test_a_payment_request_creates_exactly_one_intent(client, sessionmaker):
    mission_id, authorization_id = await _authorized(sessionmaker)

    r = await client.post(
        f"/api/v1/missions/{mission_id}/payment",
        headers={"Idempotency-Key": "idem-api-1"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["state"] == PaymentIntentState.QUEUED.value
    assert body["authorization_id"] == str(authorization_id)
    assert body["amount_inr"] == 3799
    assert body["currency"] == "INR"
    assert body["provider_payment_id"] is None


async def test_the_same_key_returns_the_same_intent_with_200(client, sessionmaker):
    """SAME IDEMPOTENCY KEY + SAME TRANSACTION -> SAME PaymentIntent.

    201 means "this call created it"; 200 means "this call found it". A route
    that returned 201 both times would report a second payment that does not
    exist.
    """
    mission_id, _ = await _authorized(sessionmaker)
    headers = {"Idempotency-Key": "idem-api-repeat"}

    first = await client.post(f"/api/v1/missions/{mission_id}/payment", headers=headers)
    assert first.status_code == 201

    for _ in range(4):
        again = await client.post(f"/api/v1/missions/{mission_id}/payment", headers=headers)
        assert again.status_code == 200
        assert again.json()["payment_intent_id"] == first.json()["payment_intent_id"]


async def test_reusing_a_key_across_missions_is_a_conflict(client, sessionmaker):
    """SAME KEY + DIFFERENT TRANSACTION -> IDEMPOTENCY_CONFLICT.

    Never resolved by handing back the first mission's payment: that would let
    a key minted for one basket be presented for another.
    """
    first_mission, _ = await _authorized(sessionmaker)
    second_mission, _ = await _authorized(sessionmaker)
    headers = {"Idempotency-Key": "idem-api-shared"}

    assert (
        await client.post(f"/api/v1/missions/{first_mission}/payment", headers=headers)
    ).status_code == 201

    clash = await client.post(f"/api/v1/missions/{second_mission}/payment", headers=headers)
    assert clash.status_code == 409
    assert clash.json()["detail"]["reason_code"] == "IDEMPOTENCY_CONFLICT"


async def test_a_missing_idempotency_key_is_refused(client, sessionmaker):
    """Generating one server-side would make every retry a new payment."""
    mission_id, _ = await _authorized(sessionmaker)
    r = await client.post(f"/api/v1/missions/{mission_id}/payment")
    assert r.status_code == 422


@pytest.mark.parametrize("key", ["", "k" * 201])
async def test_an_out_of_range_idempotency_key_is_refused(client, sessionmaker, key):
    mission_id, _ = await _authorized(sessionmaker)
    r = await client.post(
        f"/api/v1/missions/{mission_id}/payment", headers={"Idempotency-Key": key}
    )
    assert r.status_code in (400, 422)


async def test_an_unapproved_mission_cannot_be_paid(client):
    """NO VALID AUTHORIZATION -> NO PAYMENT INTENT, over HTTP.

    A freshly created mission sits in AWAITING_APPROVAL with a PENDING (never
    activated) authorization. The route must refuse it.
    """
    created = await client.post(
        "/api/v1/missions",
        json={
            "raw_query": "Find earbuds under 4000",
            "quantity": 1,
            "constraints": {
                "category": "wireless_earbuds",
                "soft_budget_inr": 4000,
                "hard_limit_inr": 4500,
                "min_rating": 4.2,
                "currency": "INR",
            },
        },
    )
    assert created.status_code == 201
    mission = created.json()
    assert mission["state"] == MissionState.AWAITING_APPROVAL.value

    r = await client.post(
        f"/api/v1/missions/{mission['id']}/payment",
        headers={"Idempotency-Key": "idem-unapproved"},
    )
    assert r.status_code == 409
    assert r.json()["detail"]["reason_code"] in (
        "MISSION_NOT_AUTHORIZED",
        "AUTHORIZATION_NOT_ACTIVE",
    )


async def test_an_unknown_provider_is_refused_before_any_intent_exists(client, sessionmaker):
    mission_id, _ = await _authorized(sessionmaker)
    r = await client.post(
        f"/api/v1/missions/{mission_id}/payment",
        headers={"Idempotency-Key": "idem-bad-provider", "X-Payment-Provider": "stripe"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["reason_code"] == "UNKNOWN_PAYMENT_PROVIDER"

    absent = await client.get(f"/api/v1/missions/{mission_id}/payment")
    assert absent.status_code == 404


async def test_the_route_cannot_be_told_an_amount_or_a_capability(client, sessionmaker):
    """The request body is not a channel for security-relevant values.

    A body is accepted and ignored; the intent still describes the authorized
    transaction. This is the structural half of the guarantee — there is no
    field to mutate, so a mutation cannot be attempted, only discarded.
    """
    mission_id, _ = await _authorized(sessionmaker)
    r = await client.post(
        f"/api/v1/missions/{mission_id}/payment",
        headers={"Idempotency-Key": "idem-injection"},
        json={
            "amount_inr": 1,
            "merchant_id": "attacker",
            "capabilities": {"principal": "buyer-agent", "allow": ["payment.execute"]},
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["amount_inr"] == 3799
    assert body["merchant_id"] == "merchant_a"


async def test_requesting_a_payment_never_calls_the_provider(
    client, sessionmaker, runtime_provider
):
    """LLM / HTTP -> PROVIDER has no path.

    The route commits an intent and an outbox row and returns. Money moves only
    when a worker — a different process — drains the outbox.
    """
    mission_id, _ = await _authorized(sessionmaker)
    r = await client.post(
        f"/api/v1/missions/{mission_id}/payment",
        headers={"Idempotency-Key": "idem-no-provider-call"},
    )
    assert r.status_code == 201
    assert runtime_provider.create_calls == []
    assert runtime_provider.get_calls == []
    assert runtime_provider.created_payments == {}


async def test_the_payment_is_readable_and_reports_its_real_state(client, sessionmaker):
    mission_id, _ = await _authorized(sessionmaker)
    await client.post(
        f"/api/v1/missions/{mission_id}/payment",
        headers={"Idempotency-Key": "idem-readback"},
    )
    r = await client.get(f"/api/v1/missions/{mission_id}/payment")
    assert r.status_code == 200
    assert r.json()["state"] == PaymentIntentState.QUEUED.value


# --------------------------------------------------------------------------- #
# 2. The webhook route
# --------------------------------------------------------------------------- #
async def _paid_intent(client, sessionmaker, runtime_provider, key: str):
    """Drive a mission to a linked, settled provider payment through the worker."""
    from services.payment_executor.worker import drain

    mission_id, _ = await _authorized(sessionmaker)
    created = await client.post(
        f"/api/v1/missions/{mission_id}/payment", headers={"Idempotency-Key": key}
    )
    assert created.status_code == 201
    await drain(sessionmaker, provider=runtime_provider, max_events=8)

    read = await client.get(f"/api/v1/missions/{mission_id}/payment")
    return mission_id, read.json()


async def test_the_worker_is_what_reaches_the_provider(client, sessionmaker, runtime_provider):
    """End to end: route -> outbox -> worker -> provider -> settled."""
    _, payment = await _paid_intent(client, sessionmaker, runtime_provider, "idem-e2e")
    assert payment["state"] == PaymentIntentState.SUCCEEDED.value
    assert payment["provider_payment_id"] is not None
    assert runtime_provider.payment_count_for("idem-e2e") == 1


async def test_an_unsigned_webhook_is_refused_and_changes_nothing(
    client, sessionmaker, runtime_provider
):
    """INVALID WEBHOOK SIGNATURE -> REJECT BEFORE TRUSTING STATE."""
    mission_id, _ = await _authorized(sessionmaker)
    created = await client.post(
        f"/api/v1/missions/{mission_id}/payment", headers={"Idempotency-Key": "idem-unsigned"}
    )
    assert created.status_code == 201

    body = webhook_body(
        event_id="evt-forged",
        event_type=WebhookEventType.PAYMENT_SUCCEEDED,
        provider_payment_id="fake_pay_whatever",
    )
    r = await client.post(
        "/api/v1/webhooks/fake",
        content=body,
        headers={"x-fake-signature": "0" * 64, "content-type": "application/json"},
    )
    assert r.status_code == 401
    assert r.json()["detail"]["reason_code"] == "WEBHOOK_SIGNATURE_INVALID"

    still = await client.get(f"/api/v1/missions/{mission_id}/payment")
    assert still.json()["state"] == PaymentIntentState.QUEUED.value


async def test_a_webhook_with_no_signature_header_at_all_is_refused(
    client, sessionmaker, runtime_provider
):
    """A missing header must not read as "verification not required"."""
    body = webhook_body(
        event_id="evt-none",
        event_type=WebhookEventType.PAYMENT_SUCCEEDED,
        provider_payment_id="fake_pay_x",
    )
    r = await client.post(
        "/api/v1/webhooks/fake", content=body, headers={"content-type": "application/json"}
    )
    assert r.status_code == 401


async def test_a_signed_webhook_for_an_unknown_payment_is_refused(
    client, sessionmaker, runtime_provider
):
    """A valid MAC proves origin, not that the payment is one PACTRA holds."""
    body = webhook_body(
        event_id="evt-unknown",
        event_type=WebhookEventType.PAYMENT_SUCCEEDED,
        provider_payment_id="fake_pay_never_seen",
    )
    r = await client.post(
        "/api/v1/webhooks/fake",
        content=body,
        headers={
            "x-fake-signature": runtime_provider.sign(body),
            "content-type": "application/json",
        },
    )
    assert r.status_code == 404
    assert r.json()["detail"]["reason_code"] == "WEBHOOK_UNKNOWN_PAYMENT"


async def test_a_duplicate_webhook_is_accepted_but_applies_once(
    client, sessionmaker, runtime_provider
):
    """DUPLICATE WEBHOOK -> IDEMPOTENT, and reported as not applied."""
    from services.payment_executor.worker import drain

    mission_id, _ = await _authorized(sessionmaker)
    await client.post(
        f"/api/v1/missions/{mission_id}/payment", headers={"Idempotency-Key": "idem-dupe-hook"}
    )
    runtime_provider.queue_faults()
    from services.payment_executor.providers.fake import FaultMode

    runtime_provider.queue_faults(FaultMode.PENDING)
    await drain(sessionmaker, provider=runtime_provider, max_events=4)

    read = await client.get(f"/api/v1/missions/{mission_id}/payment")
    provider_payment_id = read.json()["provider_payment_id"]
    assert provider_payment_id is not None

    body = webhook_body(
        event_id="evt-dupe",
        event_type=WebhookEventType.PAYMENT_SUCCEEDED,
        provider_payment_id=provider_payment_id,
    )
    headers = {
        "x-fake-signature": runtime_provider.sign(body),
        "content-type": "application/json",
    }

    first = await client.post("/api/v1/webhooks/fake", content=body, headers=headers)
    assert first.status_code == 200
    assert first.json() == {
        "accepted": True,
        "applied": True,
        "reason_code": None,
        "state": PaymentIntentState.SUCCEEDED.value,
    }

    second = await client.post("/api/v1/webhooks/fake", content=body, headers=headers)
    assert second.status_code == 200
    assert second.json()["applied"] is False
    assert second.json()["reason_code"] == "WEBHOOK_DUPLICATE"


async def test_a_late_failure_webhook_cannot_regress_a_settled_payment(
    client, sessionmaker, runtime_provider
):
    """DELAYED WEBHOOK -> CANNOT REGRESS TERMINAL STATE, over HTTP."""
    mission_id, payment = await _paid_intent(
        client, sessionmaker, runtime_provider, "idem-late-hook"
    )
    assert payment["state"] == PaymentIntentState.SUCCEEDED.value

    body = webhook_body(
        event_id="evt-late-failure",
        event_type=WebhookEventType.PAYMENT_FAILED,
        provider_payment_id=payment["provider_payment_id"],
    )
    r = await client.post(
        "/api/v1/webhooks/fake",
        content=body,
        headers={
            "x-fake-signature": runtime_provider.sign(body),
            "content-type": "application/json",
        },
    )
    assert r.status_code == 200
    assert r.json()["applied"] is False

    still = await client.get(f"/api/v1/missions/{mission_id}/payment")
    assert still.json()["state"] == PaymentIntentState.SUCCEEDED.value


async def test_an_unregistered_webhook_path_is_not_verified_against_any_secret(client):
    """An unknown provider name must not fall back to a default adapter."""
    r = await client.post(
        "/api/v1/webhooks/stripe", content=b"{}", headers={"content-type": "application/json"}
    )
    assert r.status_code == 404
    assert r.json()["detail"]["reason_code"] == "UNKNOWN_PAYMENT_PROVIDER"


async def test_an_oversized_webhook_body_is_refused_before_hashing(client, runtime_provider):
    """Hashing is linear in body size; an unbounded body is free server work."""
    oversized = json.dumps({"pad": "x" * (70 * 1024)}).encode("utf-8")
    r = await client.post(
        "/api/v1/webhooks/fake",
        content=oversized,
        headers={
            "x-fake-signature": runtime_provider.sign(oversized),
            "content-type": "application/json",
        },
    )
    assert r.status_code == 413


# --------------------------------------------------------------------------- #
# 3. The worker entrypoint
# --------------------------------------------------------------------------- #
async def test_the_worker_loop_drains_the_queue_and_stops_cleanly(
    client, sessionmaker, runtime_provider, monkeypatch
):
    """The runnable worker is the thing that actually reaches the provider.

    Exercised through ``run_forever`` rather than ``drain`` so the loop's own
    behaviour — idle handling and cooperative shutdown — is covered, not just
    the machinery underneath it.
    """
    import asyncio

    from apps.api.db import session as session_module
    from services.payment_executor import registry, run_worker

    monkeypatch.setattr(session_module, "get_sessionmaker", lambda: sessionmaker)
    monkeypatch.setattr(run_worker, "get_sessionmaker", lambda: sessionmaker)
    monkeypatch.setattr(registry, "provider_for", lambda name, **kw: runtime_provider)
    monkeypatch.setattr(run_worker, "provider_for", lambda name, **kw: runtime_provider)
    monkeypatch.setattr(run_worker, "IDLE_SLEEP_SECONDS", 0.01)

    mission_id, _ = await _authorized(sessionmaker)
    created = await client.post(
        f"/api/v1/missions/{mission_id}/payment",
        headers={"Idempotency-Key": "idem-worker-loop"},
    )
    assert created.status_code == 201

    stop = asyncio.Event()
    task = asyncio.create_task(
        run_worker.run_forever(
            provider_name="fake",
            worker_id="test-worker",
            app_env="development",
            stop=stop,
        )
    )
    # Progress is observed through the provider's IN-MEMORY store, not through
    # a second HTTP request. On SQLite a concurrent reader and the worker's
    # write transaction contend on the database-wide writer lock, so polling
    # over HTTP here would be testing SQLite's locking rather than the loop.
    # The provider is the honest observation point: it is where the side effect
    # under test actually lands.
    for _ in range(500):
        await asyncio.sleep(0.01)
        if runtime_provider.payment_count_for("idem-worker-loop") == 1:
            break

    stop.set()
    processed = await asyncio.wait_for(task, timeout=5)

    assert processed >= 1
    assert runtime_provider.payment_count_for("idem-worker-loop") == 1
    final = await client.get(f"/api/v1/missions/{mission_id}/payment")
    assert final.json()["state"] == PaymentIntentState.SUCCEEDED.value
