"""Focused contract tests for the real Razorpay TEST-mode adapter.

These tests exercise exact Orders API serialization, bounded failure
classification, receipt-based lost-response lookup, captured-payment evidence,
and Razorpay's real webhook envelope/header semantics. They never use a live
credential or claim that an HTTP stub is live-provider evidence.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from typing import Any

import httpx
import pytest
from packages.schemas.invariants import InvariantViolation
from packages.schemas.payment import (
    PaymentRequest,
    ProviderPaymentStatus,
    WebhookEventType,
    WebhookVerificationError,
)
from services.payment_executor.providers.base import (
    ProviderTerminalError,
    ProviderTimeout,
    ProviderTransientError,
)
from services.payment_executor.providers.razorpay import (
    RAZORPAY_RECEIPT_MAX_LENGTH,
    RazorpayTestPaymentProvider,
    from_environment,
    receipt_for_idempotency_key,
)

KEY_ID = "rzp_test_0000000000"
KEY_SECRET = "test-secret-not-a-credential"
WEBHOOK_SECRET = "test-webhook-secret-not-a-credential"

REQUEST = PaymentRequest(
    idempotency_key="idem-rzp-1",
    amount_inr=3799,
    currency="INR",
    merchant_id="merchant_a",
    transaction_digest_prefix="a" * 16,
)


class StubResponse:
    def __init__(self, status_code: int, body: Any = None, *, json_error: Exception | None = None):
        self.status_code = status_code
        self._body = {} if body is None else body
        self._json_error = json_error

    def json(self) -> Any:
        if self._json_error is not None:
            raise self._json_error
        return self._body


class StubClient:
    """Record calls and delegate to a response, exception, or callable."""

    def __init__(self, *, post: Any = None, get: Any = None) -> None:
        self._post = post
        self._get = get
        self.post_calls: list[tuple[str, dict[str, Any]]] = []
        self.get_calls: list[tuple[str, dict[str, Any]]] = []

    async def post(self, url: str, **kwargs: Any) -> Any:
        self.post_calls.append((url, kwargs))
        return await self._resolve(self._post, url, kwargs)

    async def get(self, url: str, **kwargs: Any) -> Any:
        self.get_calls.append((url, kwargs))
        return await self._resolve(self._get, url, kwargs)

    @staticmethod
    async def _resolve(value: Any, url: str, kwargs: dict[str, Any]) -> Any:
        if isinstance(value, Exception):
            raise value
        if callable(value):
            result = value(url, kwargs)
            return await result if hasattr(result, "__await__") else result
        return value


def make_provider(**kwargs: Any) -> RazorpayTestPaymentProvider:
    return RazorpayTestPaymentProvider(
        key_id=kwargs.pop("key_id", KEY_ID),
        key_secret=kwargs.pop("key_secret", KEY_SECRET),
        webhook_secret=kwargs.pop("webhook_secret", WEBHOOK_SECRET),
        **kwargs,
    )


def sign(body: bytes, secret: str = WEBHOOK_SECRET) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def order_entity(
    *,
    order_id: str = "order_ABC123",
    status: str = "created",
    amount: int = 379900,
    currency: str = "INR",
    receipt: str | None = None,
    attempts: int = 0,
) -> dict[str, Any]:
    return {
        "id": order_id,
        "entity": "order",
        "amount": amount,
        "amount_paid": amount if status == "paid" else 0,
        "amount_due": 0 if status == "paid" else amount,
        "currency": currency,
        "receipt": receipt or receipt_for_idempotency_key(REQUEST.idempotency_key),
        "status": status,
        "attempts": attempts,
        "notes": {},
        "created_at": 1788134400,
    }


def captured_payment(
    *,
    payment_id: str = "pay_XYZ123",
    order_id: str = "order_ABC123",
    status: str = "captured",
    captured: bool | None = True,
    amount: int = 379900,
    currency: str = "INR",
) -> dict[str, Any]:
    entity: dict[str, Any] = {
        "id": payment_id,
        "entity": "payment",
        "amount": amount,
        "currency": currency,
        "status": status,
        "order_id": order_id,
    }
    if captured is not None:
        entity["captured"] = captured
    return entity


class DuplicatePermittingRazorpay:
    """Razorpay-shaped remote that never rejects a duplicate receipt."""

    def __init__(self, *, hide_receipt_search_after_create: bool = False) -> None:
        self.orders: list[dict[str, Any]] = []
        self.post_calls = 0
        self.get_calls: list[tuple[str, dict[str, Any]]] = []
        self.hide_receipt_search_after_create = hide_receipt_search_after_create
        self.lose_next_create_response = False
        self.fail_next_search: Exception | None = None

    async def post(self, url: str, **kwargs: Any) -> StubResponse:
        assert url.endswith("/orders")
        self.post_calls += 1
        payload = kwargs["json"]
        created = order_entity(
            order_id=f"order_DUPLICATE_OK_{self.post_calls}",
            receipt=payload["receipt"],
            amount=payload["amount"],
            currency=payload["currency"],
        )
        self.orders.append(created)
        if self.lose_next_create_response:
            self.lose_next_create_response = False
            raise httpx.ReadTimeout("response lost after Razorpay accepted the Order")
        return StubResponse(200, created)

    async def get(self, url: str, **kwargs: Any) -> StubResponse:
        self.get_calls.append((url, kwargs))
        if url.endswith("/payments"):
            return StubResponse(200, {"entity": "collection", "count": 0, "items": []})
        if "/orders/order_" in url:
            order_id = url.rsplit("/", 1)[-1]
            match = next((order for order in self.orders if order["id"] == order_id), None)
            return StubResponse(404 if match is None else 200, match)

        if self.fail_next_search is not None:
            failure, self.fail_next_search = self.fail_next_search, None
            raise failure

        params = kwargs["params"]
        receipt = params["receipt"]
        matching = [order for order in self.orders if order["receipt"] == receipt]
        if self.hide_receipt_search_after_create and self.orders:
            matching = []
        count = params.get("count", 10)
        skip = params.get("skip", 0)
        page = matching[skip : skip + count]
        return StubResponse(
            200,
            {"entity": "collection", "count": len(page), "items": page},
        )


def webhook_body(
    *,
    event: str = "payment.captured",
    payment: dict[str, Any] | None = None,
    order: dict[str, Any] | None = None,
) -> bytes:
    payment = payment or captured_payment()
    payload: dict[str, Any] = {"payment": {"entity": payment}}
    if event == "order.paid":
        payload["order"] = {"entity": order or order_entity(status="paid", attempts=1)}
    body = {
        "entity": "event",
        "account_id": "acc_test",
        "event": event,
        "contains": list(payload),
        "payload": payload,
        "created_at": 1788134400,
    }
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode()


# ---------------------------------------------------------------------------
# Credentials and secret handling
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "key_id",
    ["rzp_live_0000000000", "rzp_0000000000", "", "RZP_TEST_0000000000", "rzp_test_REPLACE_ME"],
)
def test_non_test_or_placeholder_key_fails_closed(key_id: str):
    with pytest.raises(InvariantViolation) as exc:
        make_provider(key_id=key_id)
    assert exc.value.invariant == "razorpay.test_mode_only"


@pytest.mark.parametrize(
    "field,invariant,value",
    [
        ("key_secret", "razorpay.key_secret_present", ""),
        ("key_secret", "razorpay.key_secret_present", "REPLACE_ME"),
        ("webhook_secret", "razorpay.webhook_secret_present", ""),
        ("webhook_secret", "razorpay.webhook_secret_present", "REPLACE_ME"),
    ],
)
def test_missing_or_placeholder_secret_fails_closed(field: str, invariant: str, value: str):
    with pytest.raises(InvariantViolation) as exc:
        make_provider(**{field: value})
    assert exc.value.invariant == invariant


def test_from_environment_requires_credentials(monkeypatch: pytest.MonkeyPatch):
    for name in ("RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET", "RAZORPAY_WEBHOOK_SECRET"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(InvariantViolation):
        from_environment()


def test_from_environment_does_not_depend_on_duplicate_receipt_rejection_setting(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("RAZORPAY_KEY_ID", KEY_ID)
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", KEY_SECRET)
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", WEBHOOK_SECRET)
    monkeypatch.delenv("RAZORPAY_DUPLICATE_RECEIPT_REJECTION_ENABLED", raising=False)

    assert from_environment().name == "razorpay_test"


def test_production_registry_allows_configured_test_provider_without_dashboard_claim(
    monkeypatch: pytest.MonkeyPatch,
):
    from services.payment_executor.registry import provider_for

    monkeypatch.setenv("RAZORPAY_KEY_ID", KEY_ID)
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", KEY_SECRET)
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", WEBHOOK_SECRET)
    monkeypatch.delenv("RAZORPAY_DUPLICATE_RECEIPT_REJECTION_ENABLED", raising=False)

    assert provider_for("razorpay_test", app_env="production").name == "razorpay_test"


def test_fake_provider_configuration_remains_independent_of_razorpay():
    from services.payment_executor.registry import provider_for

    assert provider_for("fake", app_env="development").name == "fake"


def test_repr_and_settings_never_render_secrets(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RAZORPAY_KEY_ID", KEY_ID)
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", KEY_SECRET)
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", WEBHOOK_SECRET)
    provider = from_environment(http_client=StubClient())
    rendered = repr(provider)
    from apps.api.pactra.config import Settings

    settings_rendered = repr(Settings())
    assert KEY_SECRET not in rendered + settings_rendered
    assert WEBHOOK_SECRET not in rendered + settings_rendered
    assert "REDACTED" in rendered
    assert "**********" in settings_rendered


# ---------------------------------------------------------------------------
# Exact Orders API serialization and bounded failures
# ---------------------------------------------------------------------------
async def test_create_order_serializes_amount_currency_receipt_and_basic_auth():
    client = StubClient(post=StubResponse(200, order_entity()))
    payment = await make_provider(http_client=client).create_payment(REQUEST)

    url, kwargs = client.post_calls[0]
    assert url == "https://api.razorpay.com/v1/orders"
    assert kwargs["json"] == {
        "amount": 379900,
        "currency": "INR",
        "receipt": receipt_for_idempotency_key(REQUEST.idempotency_key),
        "notes": {
            "pactra_txn": "a" * 16,
            "pactra_idem": hashlib.sha256(REQUEST.idempotency_key.encode()).hexdigest()[:16],
        },
    }
    assert kwargs["auth"] == (KEY_ID, KEY_SECRET)
    assert isinstance(kwargs["timeout"], httpx.Timeout)
    assert payment.provider_payment_id == "order_ABC123"
    assert payment.provider_order_id == "order_ABC123"
    assert payment.provider_receipt == kwargs["json"]["receipt"]
    assert payment.provider_status == "created"
    assert payment.provider_attempts == 0
    assert payment.status is ProviderPaymentStatus.CREATED


def test_long_idempotency_key_maps_to_stable_provider_safe_receipt():
    key = "k" * 200
    first = receipt_for_idempotency_key(key)
    assert first == receipt_for_idempotency_key(key)
    assert len(first) == RAZORPAY_RECEIPT_MAX_LENGTH
    assert key not in first
    assert first != receipt_for_idempotency_key("K" * 200)


async def test_overall_timeout_bounds_even_an_injected_hanging_client():
    async def hang(_url: str, _kwargs: dict[str, Any]) -> StubResponse:
        await asyncio.sleep(1)
        return StubResponse(200, order_entity())

    provider = make_provider(http_client=StubClient(post=hang), overall_timeout_seconds=0.01)
    with pytest.raises(ProviderTimeout) as exc:
        await provider.create_payment(REQUEST)
    assert exc.value.reason_code == "PAYMENT_PROVIDER_TIMEOUT"
    assert KEY_SECRET not in exc.value.detail


async def test_transport_failure_is_ambiguous_not_retryable_failure():
    provider = make_provider(http_client=StubClient(post=httpx.ReadTimeout("lost")))
    with pytest.raises(ProviderTimeout):
        await provider.create_payment(REQUEST)


@pytest.mark.parametrize(
    "response",
    [
        StubResponse(200, ["not-an-object"]),
        StubResponse(200, json_error=ValueError("bad json")),
        StubResponse(200, {"id": "order_missing_everything"}),
        StubResponse(200, order_entity(receipt="wrong-receipt")),
        StubResponse(200, order_entity(amount=379901)),
    ],
)
async def test_malformed_create_success_is_ambiguous_and_reconcilable(response: StubResponse):
    with pytest.raises(ProviderTimeout):
        await make_provider(http_client=StubClient(post=response)).create_payment(REQUEST)


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
async def test_definitive_create_4xx_is_terminal(status: int):
    with pytest.raises(ProviderTerminalError):
        await make_provider(http_client=StubClient(post=StubResponse(status))).create_payment(
            REQUEST
        )


@pytest.mark.parametrize("status", [500, 502, 503])
async def test_create_5xx_is_ambiguous_because_order_may_exist(status: int):
    with pytest.raises(ProviderTimeout):
        await make_provider(http_client=StubClient(post=StubResponse(status))).create_payment(
            REQUEST
        )


async def test_create_429_is_retryable_and_duplicate_receipt_400_reconciles():
    with pytest.raises(ProviderTransientError):
        await make_provider(http_client=StubClient(post=StubResponse(429))).create_payment(REQUEST)

    duplicate = StubResponse(
        400, {"error": {"description": "receipt must be unique; value already exists"}}
    )
    with pytest.raises(ProviderTimeout):
        await make_provider(http_client=StubClient(post=duplicate)).create_payment(REQUEST)


# ---------------------------------------------------------------------------
# Receipt/Order reconciliation and real captured payment identity
# ---------------------------------------------------------------------------
async def test_empty_receipt_lookup_is_positive_not_found_evidence():
    client = StubClient(get=StubResponse(200, {"entity": "collection", "items": []}))
    assert (
        await make_provider(http_client=client).get_payment(idempotency_key=REQUEST.idempotency_key)
        is None
    )
    assert client.get_calls[0][1]["params"] == {
        "receipt": receipt_for_idempotency_key(REQUEST.idempotency_key),
        "count": 100,
        "skip": 0,
    }


async def test_receipt_lookup_recovers_exact_existing_order():
    order = order_entity(status="created")
    client = StubClient(get=StubResponse(200, {"entity": "collection", "items": [order]}))
    recovered = await make_provider(http_client=client).get_payment(
        idempotency_key=REQUEST.idempotency_key
    )
    assert recovered is not None
    assert recovered.provider_payment_id == "order_ABC123"
    assert recovered.idempotency_key == REQUEST.idempotency_key
    assert recovered.status is ProviderPaymentStatus.CREATED


async def test_paid_order_lookup_requires_and_persists_one_captured_payment_id():
    order = order_entity(status="paid", attempts=2)

    def get(url: str, _kwargs: dict[str, Any]) -> StubResponse:
        if url.endswith("/orders/order_ABC123/payments"):
            return StubResponse(200, {"entity": "collection", "items": [captured_payment()]})
        return StubResponse(200, {"entity": "collection", "items": [order]})

    recovered = await make_provider(http_client=StubClient(get=get)).get_payment(
        idempotency_key=REQUEST.idempotency_key
    )
    assert recovered is not None
    assert recovered.status is ProviderPaymentStatus.SUCCEEDED
    assert recovered.provider_order_id == "order_ABC123"
    assert recovered.provider_transaction_id == "pay_XYZ123"
    assert recovered.provider_attempts == 2


async def test_paid_order_without_exactly_one_captured_payment_stays_unresolved():
    def get(url: str, _kwargs: dict[str, Any]) -> StubResponse:
        if url.endswith("/payments"):
            return StubResponse(200, {"entity": "collection", "items": []})
        return StubResponse(200, order_entity(status="paid", attempts=1))

    with pytest.raises(ProviderTransientError):
        await make_provider(http_client=StubClient(get=get)).get_payment(
            provider_payment_id="order_ABC123", idempotency_key=REQUEST.idempotency_key
        )


async def test_duplicate_exact_receipt_results_are_refused_not_arbitrated():
    order = order_entity()
    response = StubResponse(200, {"items": [order, {**order, "id": "order_SECOND"}]})
    with pytest.raises(ProviderTransientError):
        await make_provider(http_client=StubClient(get=response)).get_payment(
            idempotency_key=REQUEST.idempotency_key
        )


async def test_receipt_lookup_exhausts_pages_before_adopting_one_exact_order():
    receipt = receipt_for_idempotency_key(REQUEST.idempotency_key)
    first_page = [
        order_entity(order_id="order_EXACT", receipt=receipt),
        *[
            order_entity(order_id=f"order_OTHER_{index}", receipt=f"other-{index}")
            for index in range(99)
        ],
    ]

    def get(_url: str, kwargs: dict[str, Any]) -> StubResponse:
        skip = kwargs["params"].get("skip", 0)
        return StubResponse(
            200,
            {
                "entity": "collection",
                "count": len(first_page) if skip == 0 else 0,
                "items": first_page if skip == 0 else [],
            },
        )

    client = StubClient(get=get)
    recovered = await make_provider(http_client=client).get_payment(
        idempotency_key=REQUEST.idempotency_key
    )

    assert recovered is not None
    assert recovered.provider_payment_id == "order_EXACT"
    assert [call[1]["params"] for call in client.get_calls] == [
        {"receipt": receipt, "count": 100, "skip": 0},
        {"receipt": receipt, "count": 100, "skip": 100},
    ]


async def test_receipt_lookup_detects_duplicate_exact_orders_across_pages():
    receipt = receipt_for_idempotency_key(REQUEST.idempotency_key)
    first_page = [
        order_entity(order_id="order_FIRST", receipt=receipt),
        *[
            order_entity(order_id=f"order_OTHER_{index}", receipt=f"other-{index}")
            for index in range(99)
        ],
    ]
    second_page = [
        order_entity(order_id="order_SECOND", receipt=receipt),
        *[
            order_entity(order_id=f"order_LATER_{index}", receipt=f"later-{index}")
            for index in range(99)
        ],
    ]

    def get(_url: str, kwargs: dict[str, Any]) -> StubResponse:
        skip = kwargs["params"].get("skip", 0)
        items = first_page if skip == 0 else second_page if skip == 100 else []
        return StubResponse(200, {"entity": "collection", "count": len(items), "items": items})

    client = StubClient(get=get)
    with pytest.raises(ProviderTransientError) as caught:
        await make_provider(http_client=client).get_payment(idempotency_key=REQUEST.idempotency_key)

    assert caught.value.reason_code == "PROVIDER_AMBIGUITY"
    assert [call[1]["params"]["skip"] for call in client.get_calls] == [0, 100, 200]


async def test_lookup_404_is_not_found_but_5xx_and_transport_are_not_absence():
    provider = make_provider(http_client=StubClient(get=StubResponse(404)))
    assert await provider.get_payment(provider_payment_id="order_gone") is None

    # Razorpay also uses HTTP 400 for credential and retention errors, so it is
    # not sufficiently specific to prove an Order never existed.
    with pytest.raises(ProviderTransientError):
        await make_provider(http_client=StubClient(get=StubResponse(400))).get_payment(
            provider_payment_id="order_gone"
        )
    with pytest.raises(ProviderTransientError):
        await make_provider(http_client=StubClient(get=StubResponse(503))).get_payment(
            idempotency_key=REQUEST.idempotency_key
        )
    with pytest.raises(ProviderTimeout):
        await make_provider(http_client=StubClient(get=ConnectionResetError("reset"))).get_payment(
            idempotency_key=REQUEST.idempotency_key
        )


async def _committed_razorpay_intent(sessionmaker, *, key: str):
    from packages.schemas.capability import payment_executor_capabilities
    from services.payment_executor.intents import create_payment_intent
    from tests.conftest import authorized_mission

    async with sessionmaker() as setup:
        mission, authorization, _ = await authorized_mission(setup)
        created = await create_payment_intent(
            setup,
            capabilities=payment_executor_capabilities(),
            mission_id=mission.id,
            authorization_id=authorization.authorization_id,
            idempotency_key=key,
            provider="razorpay_test",
        )
        await setup.commit()
        return mission.id, created.intent.id


async def test_existing_order_is_adopted_after_consuming_create_fence(sessionmaker):
    from apps.api.db.models import PaymentIntentRow
    from services.payment_executor.worker import run_once

    key = "razorpay-adopt-before-create"
    remote = DuplicatePermittingRazorpay()
    remote.orders.append(
        order_entity(
            order_id="order_ALREADY_THERE",
            receipt=receipt_for_idempotency_key(key),
        )
    )
    provider = make_provider(http_client=remote)
    _, intent_id = await _committed_razorpay_intent(sessionmaker, key=key)

    await run_once(sessionmaker, provider=provider)

    async with sessionmaker() as check:
        intent = await check.get(PaymentIntentRow, intent_id, populate_existing=True)
        assert intent is not None
        assert intent.provider_payment_id == "order_ALREADY_THERE"
        assert intent.provider_create_fenced_at is not None
    assert remote.post_calls == 0


async def test_multiple_existing_orders_persist_fence_and_ambiguity(sessionmaker):
    from apps.api.db.models import PaymentIntentRow
    from packages.schemas.payment import PaymentIntentState
    from services.payment_executor.worker import run_once

    key = "razorpay-ambiguous-existing-orders"
    receipt = receipt_for_idempotency_key(key)
    remote = DuplicatePermittingRazorpay()
    remote.orders.extend(
        [
            order_entity(order_id="order_AMBIGUOUS_1", receipt=receipt),
            order_entity(order_id="order_AMBIGUOUS_2", receipt=receipt),
        ]
    )
    provider = make_provider(http_client=remote)
    _, intent_id = await _committed_razorpay_intent(sessionmaker, key=key)

    await run_once(sessionmaker, provider=provider)

    async with sessionmaker() as check:
        intent = await check.get(PaymentIntentRow, intent_id, populate_existing=True)
        assert intent is not None
        assert intent.state == PaymentIntentState.PROVIDER_PENDING.value
        assert intent.provider_payment_id is None
        assert intent.provider_create_fenced_at is not None
        assert intent.provider_ambiguity_observed_at is not None
        assert intent.last_reason_code == "PROVIDER_AMBIGUITY"
    assert remote.post_calls == 0


async def test_crash_before_fence_commit_leaves_permission_unconsumed(
    sessionmaker, monkeypatch: pytest.MonkeyPatch
):
    from datetime import timedelta

    from apps.api.db.models import OutboxEventRow, PaymentIntentRow
    from packages.schemas.domain import utcnow
    from packages.schemas.payment import PaymentIntentState
    from services.payment_executor.outbox import claim_next_event
    from services.payment_executor.worker import process_claimed_event, run_once

    key = "razorpay-crash-before-fence-commit"
    remote = DuplicatePermittingRazorpay()
    provider = make_provider(http_client=remote)
    _, intent_id = await _committed_razorpay_intent(sessionmaker, key=key)
    start = utcnow()

    async with sessionmaker() as claim:
        event = await claim_next_event(claim, worker_id="doomed-before-fence", now=start)
        assert event is not None
        event_id = event.id
        await claim.commit()

    async with sessionmaker() as work:
        event = await work.get(OutboxEventRow, event_id, populate_existing=True)
        assert event is not None

        async def crash_instead_of_fence_commit() -> None:
            raise RuntimeError("process died before fence commit")

        monkeypatch.setattr(work, "commit", crash_instead_of_fence_commit)
        with pytest.raises(RuntimeError, match="before fence commit"):
            await process_claimed_event(work, provider=provider, event=event, now=start)
        await work.rollback()

    async with sessionmaker() as check:
        crashed = await check.get(PaymentIntentRow, intent_id, populate_existing=True)
        assert crashed is not None
        assert crashed.state == PaymentIntentState.QUEUED.value
        assert crashed.provider_create_fenced_at is None
    assert remote.get_calls == []
    assert remote.post_calls == 0

    await run_once(
        sessionmaker,
        provider=provider,
        now=start + timedelta(seconds=45),
    )

    async with sessionmaker() as check:
        recovered = await check.get(PaymentIntentRow, intent_id, populate_existing=True)
        assert recovered is not None
        assert recovered.state == PaymentIntentState.PROVIDER_PENDING.value
        assert recovered.provider_create_fenced_at is not None
    assert remote.post_calls == 1


async def test_crash_after_existing_search_then_empty_recovery_never_posts(
    sessionmaker, monkeypatch: pytest.MonkeyPatch
):
    from datetime import timedelta

    from apps.api.db.models import PaymentIntentRow
    from packages.schemas.domain import utcnow
    from packages.schemas.payment import PaymentIntentState
    from services.payment_executor import executor
    from services.payment_executor.worker import run_once

    key = "razorpay-existing-search-adoption-crash"
    remote = DuplicatePermittingRazorpay()
    remote.orders.append(
        order_entity(
            order_id="order_VISIBLE_ONCE",
            receipt=receipt_for_idempotency_key(key),
        )
    )
    provider = make_provider(http_client=remote)
    _, intent_id = await _committed_razorpay_intent(sessionmaker, key=key)
    start = utcnow()
    finish_existing = executor._finish_existing_before_create

    async def crash_before_adoption_commit(*args: Any, **kwargs: Any):
        raise RuntimeError("process died after search before adoption")

    monkeypatch.setattr(executor, "_finish_existing_before_create", crash_before_adoption_commit)
    with pytest.raises(RuntimeError, match="before adoption"):
        await run_once(sessionmaker, provider=provider, now=start)

    async with sessionmaker() as check:
        crashed = await check.get(PaymentIntentRow, intent_id, populate_existing=True)
        assert crashed is not None
        assert crashed.state == PaymentIntentState.QUEUED.value
        assert crashed.provider_create_fenced_at is not None
        assert crashed.provider_payment_id is None
    assert remote.post_calls == 0

    monkeypatch.setattr(executor, "_finish_existing_before_create", finish_existing)
    remote.orders.clear()  # model a later non-monotonic empty receipt search
    await run_once(sessionmaker, provider=provider, now=start + timedelta(seconds=2))

    async with sessionmaker() as check:
        recovered = await check.get(PaymentIntentRow, intent_id, populate_existing=True)
        assert recovered is not None
        assert recovered.state == PaymentIntentState.PROVIDER_PENDING.value
        assert recovered.provider_create_fenced_at is not None
        assert recovered.provider_payment_id is None
    assert remote.post_calls == 0


async def test_observed_ambiguity_is_monotonic_across_zero_and_one_match_restarts(sessionmaker):
    from datetime import timedelta

    from apps.api.db.models import PaymentIntentRow
    from packages.schemas.domain import utcnow
    from packages.schemas.payment import PaymentIntentState
    from services.payment_executor.worker import run_once

    key = "razorpay-monotonic-provider-ambiguity"
    receipt = receipt_for_idempotency_key(key)
    remote = DuplicatePermittingRazorpay()
    remote.orders.extend(
        [
            order_entity(order_id="order_AMBIGUOUS_FIRST", receipt=receipt),
            order_entity(order_id="order_AMBIGUOUS_SECOND", receipt=receipt),
        ]
    )
    provider = make_provider(http_client=remote)
    _, intent_id = await _committed_razorpay_intent(sessionmaker, key=key)
    start = utcnow()

    await run_once(sessionmaker, provider=provider, now=start)
    async with sessionmaker() as check:
        observed = await check.get(PaymentIntentRow, intent_id, populate_existing=True)
        assert observed is not None
        ambiguity_observed_at = observed.provider_ambiguity_observed_at
        assert observed.provider_create_fenced_at is not None
        assert ambiguity_observed_at is not None
        assert observed.last_reason_code == "PROVIDER_AMBIGUITY"

    remote.orders.clear()
    await run_once(sessionmaker, provider=provider, now=start + timedelta(seconds=2))
    remote.orders.append(order_entity(order_id="order_LATER_SINGLE", receipt=receipt))
    await run_once(sessionmaker, provider=provider, now=start + timedelta(seconds=5))

    async with sessionmaker() as check:
        recovered = await check.get(PaymentIntentRow, intent_id, populate_existing=True)
        assert recovered is not None
        assert recovered.state == PaymentIntentState.PROVIDER_PENDING.value
        assert recovered.provider_payment_id is None
        assert recovered.provider_ambiguity_observed_at == ambiguity_observed_at
        assert recovered.last_reason_code == "PROVIDER_AMBIGUITY"
    assert remote.post_calls == 0


async def test_timeout_with_invisible_created_order_never_issues_second_create(sessionmaker):
    """Receipt duplicates are allowed and lookup may lag, but PACTRA posts once."""
    from datetime import timedelta

    from apps.api.db.models import PaymentIntentRow
    from packages.schemas.domain import utcnow
    from packages.schemas.payment import PaymentIntentState
    from services.payment_executor.worker import run_once

    key = "razorpay-duplicate-permitted-timeout"
    remote = DuplicatePermittingRazorpay(hide_receipt_search_after_create=True)
    remote.lose_next_create_response = True
    provider = make_provider(http_client=remote)
    _, intent_id = await _committed_razorpay_intent(sessionmaker, key=key)
    start = utcnow()

    await run_once(sessionmaker, provider=provider, now=start)
    for seconds in (2, 5, 15, 45, 120):
        await run_once(
            sessionmaker,
            provider=provider,
            now=start + timedelta(seconds=seconds),
        )

    async with sessionmaker() as check:
        intent = await check.get(PaymentIntentRow, intent_id, populate_existing=True)
        assert intent is not None
        assert intent.state == PaymentIntentState.PROVIDER_PENDING.value
        assert intent.provider_create_fenced_at is not None
        assert intent.provider_payment_id is None
    assert remote.post_calls == 1
    assert len(remote.orders) == 1


async def test_crash_after_fence_before_receipt_search_restarts_search_only_without_post(
    sessionmaker,
):
    """Exact crash point: fence committed, process died before calling create."""
    from apps.api.db.models import PaymentIntentRow
    from packages.schemas.domain import utcnow
    from packages.schemas.payment import PaymentIntentState
    from services.payment_executor.worker import run_once

    key = "razorpay-crash-after-fence-before-post"
    remote = DuplicatePermittingRazorpay()
    provider = make_provider(http_client=remote)
    _, intent_id = await _committed_razorpay_intent(sessionmaker, key=key)

    async with sessionmaker() as setup:
        intent = await setup.get(PaymentIntentRow, intent_id, populate_existing=True)
        assert intent is not None
        assert intent.state == PaymentIntentState.QUEUED.value
        intent.provider_create_fenced_at = utcnow()
        await setup.commit()

    # A restarted worker must treat QUEUED + fence as uncertainty, not as an
    # illegal transition and never as permission for a replacement Order.
    await run_once(sessionmaker, provider=provider)

    async with sessionmaker() as check:
        intent = await check.get(PaymentIntentRow, intent_id, populate_existing=True)
        assert intent is not None
        assert intent.state == PaymentIntentState.PROVIDER_PENDING.value
        assert intent.provider_create_fenced_at is not None
    assert remote.get_calls
    assert remote.post_calls == 0


async def test_crash_after_empty_search_before_post_never_allows_replacement_create(
    sessionmaker, monkeypatch: pytest.MonkeyPatch
):
    from datetime import timedelta

    from apps.api.db.models import PaymentIntentRow
    from packages.schemas.domain import utcnow
    from packages.schemas.payment import PaymentIntentState
    from services.payment_executor import executor
    from services.payment_executor.worker import run_once

    key = "razorpay-crash-after-search-before-post"
    remote = DuplicatePermittingRazorpay()
    provider = make_provider(http_client=remote)
    _, intent_id = await _committed_razorpay_intent(sessionmaker, key=key)
    start = utcnow()
    original_verify = executor.verify_intent_authorization_before_provider_io
    verification_count = 0

    async def crash_before_post(*args: Any, **kwargs: Any) -> None:
        nonlocal verification_count
        verification_count += 1
        if verification_count == 3:
            raise RuntimeError("process died after empty search before POST")
        await original_verify(*args, **kwargs)

    monkeypatch.setattr(
        executor,
        "verify_intent_authorization_before_provider_io",
        crash_before_post,
    )
    with pytest.raises(RuntimeError, match="before POST"):
        await run_once(sessionmaker, provider=provider, now=start)

    async with sessionmaker() as check:
        crashed = await check.get(PaymentIntentRow, intent_id, populate_existing=True)
        assert crashed is not None
        assert crashed.state == PaymentIntentState.QUEUED.value
        assert crashed.provider_create_fenced_at is not None
        assert crashed.provider_payment_id is None
    assert remote.post_calls == 0

    monkeypatch.setattr(
        executor,
        "verify_intent_authorization_before_provider_io",
        original_verify,
    )
    await run_once(sessionmaker, provider=provider, now=start + timedelta(seconds=2))

    async with sessionmaker() as check:
        recovered = await check.get(PaymentIntentRow, intent_id, populate_existing=True)
        assert recovered is not None
        assert recovered.state == PaymentIntentState.PROVIDER_PENDING.value
        assert recovered.provider_create_fenced_at is not None
        assert recovered.provider_payment_id is None
    assert remote.post_calls == 0


async def test_remote_create_then_lost_local_commit_recovers_without_second_post(sessionmaker):
    from datetime import timedelta

    from apps.api.db.models import OutboxEventRow, PaymentIntentRow
    from packages.schemas.domain import utcnow
    from packages.schemas.payment import PaymentIntentState
    from services.payment_executor.outbox import claim_next_event
    from services.payment_executor.worker import process_claimed_event, run_once

    key = "razorpay-remote-create-local-commit-lost"
    remote = DuplicatePermittingRazorpay()
    provider = make_provider(http_client=remote)
    _, intent_id = await _committed_razorpay_intent(sessionmaker, key=key)
    start = utcnow()

    async with sessionmaker() as claim:
        event = await claim_next_event(claim, worker_id="doomed", now=start)
        assert event is not None
        event_id = event.id
        await claim.commit()

    async with sessionmaker() as crashing:
        event = await crashing.get(OutboxEventRow, event_id, populate_existing=True)
        assert event is not None
        await process_claimed_event(
            crashing,
            provider=provider,
            event=event,
            now=start,
        )
        assert remote.post_calls == 1
        await crashing.rollback()

    async with sessionmaker() as check:
        rolled_back = await check.get(PaymentIntentRow, intent_id, populate_existing=True)
        assert rolled_back is not None
        assert rolled_back.state == PaymentIntentState.QUEUED.value
        assert rolled_back.provider_create_fenced_at is not None
        assert rolled_back.provider_payment_id is None

    await run_once(
        sessionmaker,
        provider=provider,
        worker_id="recovering",
        now=start + timedelta(seconds=45),
    )

    async with sessionmaker() as check:
        recovered = await check.get(PaymentIntentRow, intent_id, populate_existing=True)
        assert recovered is not None
        assert recovered.provider_payment_id == "order_DUPLICATE_OK_1"
        assert recovered.provider_create_fenced_at is not None
    assert remote.post_calls == 1
    assert len(remote.orders) == 1


async def test_duplicate_create_event_redelivery_from_fenced_state_cannot_create_orders(
    sessionmaker,
):
    from apps.api.db.models import PaymentIntentRow
    from packages.schemas.domain import utcnow
    from packages.schemas.payment import OutboxEventType
    from services.payment_executor.outbox import enqueue_outbox_event
    from services.payment_executor.worker import run_once

    key = "razorpay-concurrent-fenced-redelivery"
    remote = DuplicatePermittingRazorpay()
    provider = make_provider(http_client=remote)
    _, intent_id = await _committed_razorpay_intent(sessionmaker, key=key)

    async with sessionmaker() as setup:
        intent = await setup.get(PaymentIntentRow, intent_id, populate_existing=True)
        assert intent is not None
        intent.provider_create_fenced_at = utcnow()
        await enqueue_outbox_event(
            setup,
            payment_intent_id=intent_id,
            event_type=OutboxEventType.PAYMENT_CREATE_REQUESTED,
            payload={"idempotency_key": key},
        )
        await setup.commit()

    await run_once(sessionmaker, provider=provider, worker_id="worker-a")
    await run_once(sessionmaker, provider=provider, worker_id="worker-b")

    assert remote.post_calls == 0
    assert len(remote.orders) == 0


async def test_lost_create_response_recovers_same_remote_order_and_logical_intent(sessionmaker):
    """Flagship path: remote side effect survives a lost create response."""
    from datetime import timedelta

    from apps.api.db.models import PaymentIntentRow
    from packages.schemas.capability import payment_executor_capabilities
    from packages.schemas.domain import EventType, utcnow
    from packages.schemas.payment import PaymentIntentState
    from services.audit_ledger.ledger import list_events
    from services.payment_executor.intents import create_payment_intent
    from services.payment_executor.worker import run_once
    from sqlalchemy import func, select
    from tests.conftest import authorized_mission

    class RemoteRazorpay:
        def __init__(self) -> None:
            self.orders: dict[str, dict[str, Any]] = {}
            self.create_calls = 0
            self.lose_first_create_response = True
            self.captured = False

        async def post(self, url: str, **kwargs: Any) -> StubResponse:
            assert url.endswith("/orders")
            self.create_calls += 1
            payload = kwargs["json"]
            remote = order_entity(
                receipt=payload["receipt"],
                amount=payload["amount"],
                currency=payload["currency"],
            )
            self.orders[payload["receipt"]] = remote
            if self.lose_first_create_response:
                self.lose_first_create_response = False
                raise httpx.ReadTimeout("response lost after remote commit")
            return StubResponse(200, remote)

        async def get(self, url: str, **kwargs: Any) -> StubResponse:
            if url.endswith("/payments"):
                items = [captured_payment()] if self.captured else []
                return StubResponse(200, {"entity": "collection", "items": items})
            if "/orders/order_" in url:
                return StubResponse(200, next(iter(self.orders.values())))
            receipt = kwargs["params"]["receipt"]
            remote = self.orders.get(receipt)
            return StubResponse(
                200,
                {"entity": "collection", "items": [] if remote is None else [remote]},
            )

    remote = RemoteRazorpay()
    provider = make_provider(http_client=remote)
    async with sessionmaker() as setup:
        mission, authorization, _ = await authorized_mission(setup)
        created = await create_payment_intent(
            setup,
            capabilities=payment_executor_capabilities(),
            mission_id=mission.id,
            authorization_id=authorization.authorization_id,
            idempotency_key=REQUEST.idempotency_key,
            provider="razorpay_test",
        )
        mission_id, intent_id = mission.id, created.intent.id
        await setup.commit()

    # Preflight sees no Order; create commits remotely then loses its response.
    await run_once(sessionmaker, provider=provider)
    async with sessionmaker() as check:
        uncertain = await check.get(PaymentIntentRow, intent_id, populate_existing=True)
        assert uncertain is not None
        assert uncertain.state == PaymentIntentState.PROVIDER_PENDING.value
        assert uncertain.provider_payment_id is None
    assert remote.create_calls == 1
    assert len(remote.orders) == 1

    # Reconciliation adopts the exact Order without a second POST or intent.
    await run_once(sessionmaker, provider=provider)
    async with sessionmaker() as check:
        recovered = await check.get(PaymentIntentRow, intent_id, populate_existing=True)
        assert recovered is not None
        assert recovered.provider_payment_id == "order_ABC123"
        assert recovered.provider_order_id == "order_ABC123"
        assert recovered.provider_receipt == receipt_for_idempotency_key(REQUEST.idempotency_key)
        logical_count = await check.scalar(
            select(func.count(PaymentIntentRow.id)).where(
                PaymentIntentRow.idempotency_key == REQUEST.idempotency_key
            )
        )
        assert logical_count == 1
    assert remote.create_calls == 1

    # Model the later CUSTOMER CHECKOUT result remotely; authenticated polling
    # records the real pay_... id before declaring success.
    remote.captured = True
    stored_order = next(iter(remote.orders.values()))
    stored_order.update(status="paid", attempts=1, amount_paid=379900, amount_due=0)
    await run_once(sessionmaker, provider=provider, now=utcnow() + timedelta(seconds=60))
    async with sessionmaker() as check:
        settled = await check.get(PaymentIntentRow, intent_id, populate_existing=True)
        assert settled is not None
        assert settled.state == PaymentIntentState.SUCCEEDED.value
        assert settled.provider_payment_id == "order_ABC123"
        assert settled.provider_transaction_id == "pay_XYZ123"
        events = await list_events(check, mission_id)
        event_types = [event.event_type for event in events]
        audit_json = json.dumps([event.payload for event in events], sort_keys=True)
    assert EventType.PAYMENT_PROVIDER_TIMEOUT.value in event_types
    assert EventType.PAYMENT_RECONCILED.value in event_types
    assert EventType.PAYMENT_SUCCEEDED.value in event_types
    assert KEY_SECRET not in audit_json
    assert WEBHOOK_SECRET not in audit_json
    assert remote.create_calls == 1


async def _pending_razorpay_intent(sessionmaker, *, key: str):
    from packages.schemas.capability import payment_executor_capabilities
    from services.payment_executor.intents import create_payment_intent
    from services.payment_executor.worker import run_once
    from tests.conftest import authorized_mission

    receipt = receipt_for_idempotency_key(key)
    client = StubClient(
        get=StubResponse(200, {"entity": "collection", "items": []}),
        post=StubResponse(200, order_entity(receipt=receipt)),
    )
    provider = make_provider(http_client=client)
    async with sessionmaker() as setup:
        mission, authorization, _ = await authorized_mission(setup)
        created = await create_payment_intent(
            setup,
            capabilities=payment_executor_capabilities(),
            mission_id=mission.id,
            authorization_id=authorization.authorization_id,
            idempotency_key=key,
            provider="razorpay_test",
        )
        mission_id, intent_id = mission.id, created.intent.id
        await setup.commit()
    await run_once(sessionmaker, provider=provider)
    return provider, mission_id, intent_id


async def test_real_razorpay_webhook_evidence_settles_once_and_deduplicates(sessionmaker):
    from apps.api.db.models import PaymentIntentRow, WebhookEventRow
    from packages.schemas.payment import PaymentIntentState
    from services.payment_executor.webhooks import handle_webhook
    from sqlalchemy import func, select

    provider, _, intent_id = await _pending_razorpay_intent(
        sessionmaker, key="razorpay-webhook-success"
    )
    body = webhook_body()
    signature = sign(body)
    async with sessionmaker() as session:
        first = await handle_webhook(
            session,
            provider=provider,
            body=body,
            signature=signature,
            provider_event_id="evt_real_1",
        )
        await session.commit()
    assert first.applied is True
    assert first.state is PaymentIntentState.SUCCEEDED

    async with sessionmaker() as session:
        duplicate = await handle_webhook(
            session,
            provider=provider,
            body=body,
            signature=signature,
            provider_event_id="evt_real_1",
        )
        await session.commit()
    assert duplicate.accepted is True
    assert duplicate.applied is False
    assert duplicate.reason_code == "WEBHOOK_DUPLICATE"

    async with sessionmaker() as session:
        intent = await session.get(PaymentIntentRow, intent_id, populate_existing=True)
        assert intent is not None
        assert intent.provider_payment_id == "order_ABC123"
        assert intent.provider_order_id == "order_ABC123"
        assert intent.provider_transaction_id == "pay_XYZ123"
        assert intent.provider_status == "captured"
        count = await session.scalar(select(func.count(WebhookEventRow.id)))
        assert count == 1


async def test_invalid_razorpay_webhook_changes_nothing_and_failed_attempt_stays_pending(
    sessionmaker,
):
    from apps.api.db.models import PaymentIntentRow, WebhookEventRow
    from packages.schemas.payment import PaymentIntentState
    from services.payment_executor.webhooks import WebhookRejected, handle_webhook
    from sqlalchemy import func, select

    provider, _, intent_id = await _pending_razorpay_intent(
        sessionmaker, key="razorpay-webhook-failure"
    )
    captured_body = webhook_body()
    async with sessionmaker() as session:
        with pytest.raises(WebhookRejected) as invalid:
            await handle_webhook(
                session,
                provider=provider,
                body=captured_body,
                signature="0" * 64,
                provider_event_id="evt_forged",
            )
        assert invalid.value.reason_code == "WEBHOOK_SIGNATURE_INVALID"
        await session.rollback()

    failed_entity = captured_payment(payment_id="pay_FAILED", status="failed", captured=False)
    failed_body = webhook_body(event="payment.failed", payment=failed_entity)
    async with sessionmaker() as session:
        failed = await handle_webhook(
            session,
            provider=provider,
            body=failed_body,
            signature=sign(failed_body),
            provider_event_id="evt_failed_attempt",
        )
        await session.commit()
    assert failed.applied is False
    assert failed.state is PaymentIntentState.PROVIDER_PENDING
    assert failed.reason_code == "PROVIDER_PAYMENT_ATTEMPT_FAILED"

    async with sessionmaker() as session:
        intent = await session.get(PaymentIntentRow, intent_id, populate_existing=True)
        assert intent is not None
        assert intent.state == PaymentIntentState.PROVIDER_PENDING.value
        # A failed attempt id cannot occupy the final settlement identity.
        assert intent.provider_transaction_id is None
        assert intent.last_reason_code == "PROVIDER_PAYMENT_ATTEMPT_FAILED"
        count = await session.scalar(select(func.count(WebhookEventRow.id)))
        assert count == 1


async def test_api_route_uses_razorpay_event_id_header_and_never_returns_secrets(
    client,
    sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
):
    from apps.api.pactra.config import get_settings

    await _pending_razorpay_intent(sessionmaker, key="razorpay-route-webhook")
    monkeypatch.setenv("RAZORPAY_KEY_ID", KEY_ID)
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", KEY_SECRET)
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", WEBHOOK_SECRET)
    get_settings.cache_clear()
    body = webhook_body()
    response = await client.post(
        "/api/v1/webhooks/razorpay_test",
        content=body,
        headers={
            "X-Razorpay-Signature": sign(body),
            "X-Razorpay-Event-Id": "evt_route_1",
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json() == {
        "accepted": True,
        "applied": True,
        "reason_code": None,
        "state": "SUCCEEDED",
    }
    assert KEY_SECRET not in response.text
    assert WEBHOOK_SECRET not in response.text
    get_settings.cache_clear()


async def test_api_route_rejects_non_ascii_signature_without_state_or_authority_effect(
    client,
    sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
):
    from apps.api.db.models import AuthorizationRow, PaymentIntentRow, WebhookEventRow
    from apps.api.pactra.config import get_settings
    from services.audit_ledger.ledger import list_events
    from sqlalchemy import func, select

    _, mission_id, intent_id = await _pending_razorpay_intent(
        sessionmaker, key="razorpay-route-non-ascii-signature"
    )
    monkeypatch.setenv("RAZORPAY_KEY_ID", KEY_ID)
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", KEY_SECRET)
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", WEBHOOK_SECRET)
    get_settings.cache_clear()

    async with sessionmaker() as check:
        before_intent = await check.get(PaymentIntentRow, intent_id)
        before_authorization = await check.scalar(
            select(AuthorizationRow).where(AuthorizationRow.mission_id == mission_id)
        )
        assert before_intent is not None
        assert before_authorization is not None
        payment_before = (
            before_intent.state,
            before_intent.provider_payment_id,
            before_intent.provider_order_id,
            before_intent.provider_transaction_id,
            before_intent.provider_receipt,
            before_intent.provider_status,
            before_intent.provider_attempts,
            before_intent.attempts,
            before_intent.last_reason_code,
            before_intent.updated_at,
        )
        authority_before = (before_authorization.status, before_authorization.consumed_at)
        audit_before = [event.event_id for event in await list_events(check, mission_id)]
        webhooks_before = await check.scalar(select(func.count(WebhookEventRow.id)))

    body = webhook_body()
    response = await client.post(
        "/api/v1/webhooks/razorpay_test",
        content=body,
        headers=[
            (b"X-Razorpay-Signature", b"\xff"),
            (b"X-Razorpay-Event-Id", b"evt_non_ascii_signature"),
            (b"Content-Type", b"application/json"),
        ],
    )

    assert response.status_code == 401, response.text
    assert response.json() == {"detail": {"reason_code": "WEBHOOK_SIGNATURE_INVALID"}}
    assert KEY_SECRET not in response.text
    assert WEBHOOK_SECRET not in response.text

    async with sessionmaker() as check:
        after_intent = await check.get(PaymentIntentRow, intent_id)
        after_authorization = await check.scalar(
            select(AuthorizationRow).where(AuthorizationRow.mission_id == mission_id)
        )
        assert after_intent is not None
        assert after_authorization is not None
        assert (
            after_intent.state,
            after_intent.provider_payment_id,
            after_intent.provider_order_id,
            after_intent.provider_transaction_id,
            after_intent.provider_receipt,
            after_intent.provider_status,
            after_intent.provider_attempts,
            after_intent.attempts,
            after_intent.last_reason_code,
            after_intent.updated_at,
        ) == payment_before
        assert (after_authorization.status, after_authorization.consumed_at) == authority_before
        assert [event.event_id for event in await list_events(check, mission_id)] == audit_before
        assert await check.scalar(select(func.count(WebhookEventRow.id))) == webhooks_before

    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Real Razorpay webhook envelope and transport event id
# ---------------------------------------------------------------------------
def test_valid_captured_webhook_uses_header_event_id_and_preserves_pay_id():
    body = webhook_body()
    event = make_provider().verify_webhook(
        body=body,
        signature=sign(body),
        provider_event_id="evt_header_1",
    )
    assert event.provider_event_id == "evt_header_1"
    assert event.provider_payment_id == "order_ABC123"
    assert event.provider_order_id == "order_ABC123"
    assert event.provider_transaction_id == "pay_XYZ123"
    assert event.amount_inr == 3799
    assert event.currency == "INR"
    assert event.event_type is WebhookEventType.PAYMENT_SUCCEEDED


def test_invalid_signature_is_rejected_before_event_header_or_payload_matters():
    body = webhook_body()
    with pytest.raises(WebhookVerificationError) as exc:
        make_provider().verify_webhook(body=body, signature="0" * 64, provider_event_id="evt_1")
    assert exc.value.reason_code == "WEBHOOK_SIGNATURE_INVALID"


def test_valid_signature_without_event_id_is_rejected_for_idempotency():
    body = webhook_body()
    with pytest.raises(WebhookVerificationError) as exc:
        make_provider().verify_webhook(body=body, signature=sign(body))
    assert exc.value.reason_code == "WEBHOOK_EVENT_ID_MISSING"


@pytest.mark.parametrize(
    "body",
    [b"not-json", b"[]", webhook_body(event="payment.dispute.created")],
)
def test_signed_malformed_or_unsupported_payload_is_rejected(body: bytes):
    with pytest.raises(WebhookVerificationError) as exc:
        make_provider().verify_webhook(body=body, signature=sign(body), provider_event_id="evt_bad")
    assert exc.value.reason_code == "WEBHOOK_PAYLOAD_INVALID"


def test_tampering_after_signature_changes_is_rejected():
    original = webhook_body()
    tampered = webhook_body(payment=captured_payment(order_id="order_ATTACKER"))
    with pytest.raises(WebhookVerificationError):
        make_provider().verify_webhook(
            body=tampered, signature=sign(original), provider_event_id="evt_1"
        )


def test_payment_failed_maps_to_pending_attempt_not_terminal_failure():
    failed = captured_payment(status="failed", captured=False, payment_id="pay_FAILED")
    body = webhook_body(event="payment.failed", payment=failed)
    event = make_provider().verify_webhook(
        body=body, signature=sign(body), provider_event_id="evt_failed"
    )
    assert event.event_type is WebhookEventType.PAYMENT_ATTEMPT_FAILED


def test_success_event_requires_captured_provider_evidence():
    not_captured = captured_payment(status="captured", captured=False)
    body = webhook_body(payment=not_captured)
    with pytest.raises(WebhookVerificationError) as exc:
        make_provider().verify_webhook(
            body=body, signature=sign(body), provider_event_id="evt_false_success"
        )
    assert exc.value.reason_code == "WEBHOOK_PAYLOAD_INVALID"


def test_order_paid_entities_must_agree_and_expose_attempts():
    body = webhook_body(event="order.paid")
    event = make_provider().verify_webhook(
        body=body, signature=sign(body), provider_event_id="evt_paid"
    )
    assert event.event_type is WebhookEventType.PAYMENT_SUCCEEDED
    assert event.provider_attempts == 1

    mismatch = webhook_body(
        event="order.paid", order=order_entity(status="paid", amount=100, attempts=1)
    )
    with pytest.raises(WebhookVerificationError):
        make_provider().verify_webhook(
            body=mismatch, signature=sign(mismatch), provider_event_id="evt_mismatch"
        )
