"""Real Razorpay TEST MODE provider.

PACTRA creates a Razorpay Order server-side. It never attempts to collect card
or other payment-instrument details: the customer completes Razorpay Checkout,
and PACTRA learns the result from a signed webhook or an authenticated API
lookup. An Order is therefore provider-pending until Razorpay reports it paid
and a captured ``pay_...`` entity can be identified.

Lost create responses are recovered by a deterministic, provider-safe receipt.
Razorpay receipts are limited to 40 characters, while PACTRA idempotency keys
may be 200 characters, so the adapter sends ``pactra_`` plus 132 bits of the
key's SHA-256 digest. The same input always produces the same receipt and the
original key never leaves PACTRA.

Every network call has two independent bounds: explicit httpx connect/read/
write/pool timeouts and an overall wall-clock timeout. A create transport
failure, malformed success response, or 5xx is ambiguous and becomes
``ProviderTimeout``; it is never treated as proof that no Order was created.

Secrets are loaded through PACTRA settings, retained only in private
attributes, omitted from repr/audit/API output, and used solely for HTTP Basic
Auth or webhook HMAC verification. Live keys are structurally refused.

At-most-one remote Order additionally depends on Razorpay's merchant setting
"reject orders with duplicate receipts". Provider construction requires an
operator acknowledgement that this setting is enabled; PACTRA cannot configure
or independently verify that dashboard setting.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any

import httpx
from packages.schemas.invariants import require
from packages.schemas.payment import (
    PaymentRequest,
    ProviderPayment,
    ProviderPaymentStatus,
    VerifiedWebhookEvent,
    WebhookEventType,
    WebhookVerificationError,
)

from services.payment_executor.providers.base import (
    ProviderTerminalError,
    ProviderTimeout,
    ProviderTransientError,
)

PROVIDER_NAME = "razorpay_test"
TEST_KEY_PREFIX = "rzp_test_"
API_BASE = "https://api.razorpay.com/v1"

RAZORPAY_RECEIPT_MAX_LENGTH = 40
_RECEIPT_PREFIX = "pactra_"
_RECEIPT_DIGEST_LENGTH = RAZORPAY_RECEIPT_MAX_LENGTH - len(_RECEIPT_PREFIX)

_ORDER_STATUS_MAP: dict[str, ProviderPaymentStatus] = {
    "created": ProviderPaymentStatus.CREATED,
    "attempted": ProviderPaymentStatus.PENDING,
    # A paid Order is accepted as success only after _attach_captured_payment
    # finds the captured pay_... entity through the authenticated API.
    "paid": ProviderPaymentStatus.SUCCEEDED,
}


class RazorpayTestModeViolation(Exception):
    """Compatibility name for callers that classify test-mode refusal."""

    reason_code = "RAZORPAY_TEST_MODE_REQUIRED"


def receipt_for_idempotency_key(idempotency_key: str) -> str:
    """Return a deterministic Razorpay receipt that never exceeds 40 chars."""
    digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
    return f"{_RECEIPT_PREFIX}{digest[:_RECEIPT_DIGEST_LENGTH]}"


def _is_configured_secret(value: str) -> bool:
    return bool(value) and value != "REPLACE_ME"


class RazorpayTestPaymentProvider:
    """Razorpay Orders/Payments adapter restricted to test credentials."""

    name = PROVIDER_NAME

    def __init__(
        self,
        *,
        key_id: str,
        key_secret: str,
        webhook_secret: str,
        duplicate_receipt_rejection_enabled: bool = False,
        http_client: Any = None,
        connect_timeout_seconds: float = 3.0,
        read_timeout_seconds: float = 7.0,
        write_timeout_seconds: float = 5.0,
        pool_timeout_seconds: float = 2.0,
        overall_timeout_seconds: float = 10.0,
    ) -> None:
        require(
            key_id.startswith(TEST_KEY_PREFIX) and key_id != "rzp_test_REPLACE_ME",
            "razorpay.test_mode_only",
            "RAZORPAY_KEY_ID must be a configured Razorpay TEST key; live keys are refused",
        )
        require(
            duplicate_receipt_rejection_enabled is True,
            "razorpay.duplicate_receipt_rejection_acknowledged",
            "RAZORPAY_DUPLICATE_RECEIPT_REJECTION_ENABLED=true must acknowledge that "
            "'reject orders with duplicate receipts' is enabled in the Razorpay dashboard; "
            "PACTRA does not configure this provider setting",
        )
        require(
            _is_configured_secret(key_secret),
            "razorpay.key_secret_present",
            "RAZORPAY_KEY_SECRET is not configured",
        )
        require(
            _is_configured_secret(webhook_secret),
            "razorpay.webhook_secret_present",
            "RAZORPAY_WEBHOOK_SECRET is not configured",
        )
        for name, value in {
            "connect": connect_timeout_seconds,
            "read": read_timeout_seconds,
            "write": write_timeout_seconds,
            "pool": pool_timeout_seconds,
            "overall": overall_timeout_seconds,
        }.items():
            require(value > 0, f"razorpay.{name}_timeout_positive", f"{name} timeout must be > 0")

        self.key_id = key_id
        self._key_secret = key_secret
        self._webhook_secret = webhook_secret
        self._http = http_client
        self._http_timeout = httpx.Timeout(
            connect=connect_timeout_seconds,
            read=read_timeout_seconds,
            write=write_timeout_seconds,
            pool=pool_timeout_seconds,
        )
        self._overall_timeout = overall_timeout_seconds

    def __repr__(self) -> str:
        return f"<RazorpayTestPaymentProvider key_id={self.key_id!r} secrets=REDACTED>"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Perform one bounded request without ever placing credentials in a URL."""

        async def send() -> Any:
            if self._http is not None:
                call = getattr(self._http, method.lower())
                kwargs: dict[str, Any] = {
                    "auth": (self.key_id, self._key_secret),
                    "timeout": self._http_timeout,
                }
                if json_body is not None:
                    kwargs["json"] = json_body
                if params is not None:
                    kwargs["params"] = params
                return await call(f"{API_BASE}{path}", **kwargs)

            async with httpx.AsyncClient(
                base_url=API_BASE,
                auth=httpx.BasicAuth(self.key_id, self._key_secret),
                timeout=self._http_timeout,
                headers={"Accept": "application/json"},
            ) as client:
                return await client.request(method, path, json=json_body, params=params)

        try:
            async with asyncio.timeout(self._overall_timeout):
                return await send()
        except (TimeoutError, OSError, httpx.HTTPError) as exc:
            # Deliberately no exception string: transport messages may contain
            # implementation details. The type is enough for stable diagnosis.
            raise ProviderTimeout(
                self.name, f"bounded {method.upper()} transport failure ({type(exc).__name__})"
            ) from exc

    @staticmethod
    def _status_code(response: Any) -> int:
        try:
            return int(response.status_code)
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError("response has no valid HTTP status") from exc

    @staticmethod
    def _json_object(response: Any) -> dict[str, Any]:
        try:
            parsed = response.json()
        except Exception as exc:  # noqa: BLE001 - provider JSON is untrusted
            raise ValueError("response body is not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError("response body is not a JSON object")
        return parsed

    @staticmethod
    def _whole_rupees(value: Any, *, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{field} is not a non-negative integer")
        if value % 100 != 0:
            raise ValueError(f"{field} cannot be represented as whole INR")
        return value // 100

    @staticmethod
    def _non_negative_int(value: Any, *, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{field} is not a non-negative integer")
        return value

    def _order_to_payment(
        self,
        order: dict[str, Any],
        *,
        expected_idempotency_key: str | None,
    ) -> ProviderPayment:
        order_id = order.get("id")
        if not isinstance(order_id, str) or not order_id.startswith("order_"):
            raise ValueError("order id is missing or malformed")
        if order.get("entity") != "order":
            raise ValueError("response entity is not an order")

        raw_status = order.get("status")
        if not isinstance(raw_status, str) or not raw_status:
            raise ValueError("order status is missing or malformed")
        amount_inr = self._whole_rupees(order.get("amount"), field="order.amount")
        currency = order.get("currency")
        if not isinstance(currency, str) or len(currency) != 3:
            raise ValueError("order currency is missing or malformed")
        receipt = order.get("receipt")
        if not isinstance(receipt, str) or not receipt:
            raise ValueError("order receipt is missing or malformed")
        if expected_idempotency_key is not None:
            expected_receipt = receipt_for_idempotency_key(expected_idempotency_key)
            if not hmac.compare_digest(receipt, expected_receipt):
                raise ValueError("order receipt does not match the requested logical payment")
        attempts = self._non_negative_int(order.get("attempts"), field="order.attempts")

        return ProviderPayment(
            provider=self.name,
            provider_payment_id=order_id,
            provider_order_id=order_id,
            status=_ORDER_STATUS_MAP.get(raw_status, ProviderPaymentStatus.PENDING),
            amount_inr=amount_inr,
            currency=currency,
            idempotency_key=expected_idempotency_key,
            provider_receipt=receipt,
            provider_status=raw_status,
            provider_attempts=attempts,
        )

    async def _attach_captured_payment(self, payment: ProviderPayment) -> ProviderPayment:
        """Resolve the real ``pay_...`` id for an Order Razorpay calls paid."""
        response = await self._request("GET", f"/orders/{payment.provider_payment_id}/payments")
        try:
            status_code = self._status_code(response)
        except ValueError as exc:
            raise ProviderTransientError(
                self.name, f"malformed HTTP response while fetching captured payment: {exc}"
            ) from exc
        if not 200 <= status_code < 300:
            raise ProviderTransientError(
                self.name, f"HTTP {status_code} while fetching payments for paid order"
            )
        try:
            parsed = self._json_object(response)
            items = parsed.get("items")
            if not isinstance(items, list):
                raise ValueError("payments collection has no items list")
            captured: list[str] = []
            for item in items:
                if not isinstance(item, dict) or item.get("status") != "captured":
                    continue
                payment_id = item.get("id")
                if not isinstance(payment_id, str) or not payment_id.startswith("pay_"):
                    raise ValueError("captured payment id is malformed")
                if item.get("order_id") != payment.provider_order_id:
                    raise ValueError("captured payment names a different order")
                amount = self._whole_rupees(item.get("amount"), field="payment.amount")
                if amount != payment.amount_inr or item.get("currency") != payment.currency:
                    raise ValueError("captured payment amount or currency mismatches its order")
                captured.append(payment_id)
        except ValueError as exc:
            raise ProviderTransientError(self.name, f"malformed payments response: {exc}") from exc

        if len(captured) != 1:
            raise ProviderTransientError(
                self.name,
                f"paid order exposes {len(captured)} matching captured payments; "
                "expected exactly one",
            )
        return payment.model_copy(update={"provider_transaction_id": captured[0]})

    @staticmethod
    def _duplicate_receipt_response(response: Any) -> bool:
        try:
            parsed = response.json()
        except Exception:  # noqa: BLE001 - only classification, never trust
            return False
        error = parsed.get("error") if isinstance(parsed, dict) else None
        if not isinstance(error, dict):
            return False
        description = error.get("description")
        if not isinstance(description, str):
            return False
        lowered = description.lower()
        return "receipt" in lowered and ("already" in lowered or "unique" in lowered)

    async def create_payment(self, request: PaymentRequest) -> ProviderPayment:
        """Create a real Razorpay TEST Order, never a server-side card payment."""
        receipt = receipt_for_idempotency_key(request.idempotency_key)
        payload = {
            "amount": request.amount_inr * 100,
            "currency": request.currency,
            "receipt": receipt,
            "notes": {
                "pactra_txn": request.transaction_digest_prefix,
                "pactra_idem": hashlib.sha256(request.idempotency_key.encode("utf-8")).hexdigest()[
                    :16
                ],
            },
        }
        response = await self._request("POST", "/orders", json_body=payload)
        try:
            status_code = self._status_code(response)
        except ValueError as exc:
            raise ProviderTimeout(self.name, f"ambiguous malformed create response: {exc}") from exc

        if 200 <= status_code < 300:
            try:
                payment = self._order_to_payment(
                    self._json_object(response),
                    expected_idempotency_key=request.idempotency_key,
                )
            except ValueError as exc:
                # Razorpay may have created the Order before returning an
                # unusable response. Reconciliation, never a blind retry.
                raise ProviderTimeout(
                    self.name, f"ambiguous malformed create response: {exc}"
                ) from exc
            if payment.status is ProviderPaymentStatus.SUCCEEDED:
                return await self._attach_captured_payment(payment)
            return payment

        if status_code >= 500:
            raise ProviderTimeout(
                self.name, f"ambiguous HTTP {status_code} response to order creation"
            )
        if status_code == 429:
            raise ProviderTransientError(self.name, "HTTP 429 from Razorpay")
        if status_code == 400 and self._duplicate_receipt_response(response):
            raise ProviderTimeout(
                self.name, "duplicate receipt response requires Order reconciliation"
            )
        raise ProviderTerminalError(self.name, f"HTTP {status_code} from Razorpay")

    async def get_payment(
        self,
        *,
        provider_payment_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> ProviderPayment | None:
        """Fetch an Order by id or recover it by the deterministic receipt."""
        if provider_payment_id is None and idempotency_key is None:
            return None

        if provider_payment_id is not None:
            response = await self._request("GET", f"/orders/{provider_payment_id}")
            try:
                status_code = self._status_code(response)
            except ValueError as exc:
                raise ProviderTransientError(
                    self.name, f"malformed HTTP response while fetching Razorpay Order: {exc}"
                ) from exc
            if status_code == 404:
                return None
            if not 200 <= status_code < 300:
                raise ProviderTransientError(
                    self.name, f"HTTP {status_code} while fetching Razorpay Order"
                )
            try:
                payment = self._order_to_payment(
                    self._json_object(response),
                    expected_idempotency_key=idempotency_key,
                )
            except ValueError as exc:
                raise ProviderTransientError(
                    self.name, f"malformed Order lookup response: {exc}"
                ) from exc
        else:
            assert idempotency_key is not None
            receipt = receipt_for_idempotency_key(idempotency_key)
            response = await self._request("GET", "/orders", params={"receipt": receipt})
            try:
                status_code = self._status_code(response)
            except ValueError as exc:
                raise ProviderTransientError(
                    self.name, f"malformed HTTP response while searching Razorpay Orders: {exc}"
                ) from exc
            if not 200 <= status_code < 300:
                raise ProviderTransientError(
                    self.name, f"HTTP {status_code} while searching Razorpay Orders"
                )
            try:
                parsed = self._json_object(response)
                items = parsed.get("items")
                if not isinstance(items, list):
                    raise ValueError("orders collection has no items list")
                exact = [
                    item
                    for item in items
                    if isinstance(item, dict) and item.get("receipt") == receipt
                ]
                if not exact:
                    return None
                if len(exact) > 1:
                    raise ProviderTransientError(
                        self.name,
                        f"{len(exact)} Razorpay Orders share one PACTRA receipt; "
                        "refusing ambiguity",
                    )
                payment = self._order_to_payment(exact[0], expected_idempotency_key=idempotency_key)
            except ProviderTransientError:
                raise
            except ValueError as exc:
                raise ProviderTransientError(
                    self.name, f"malformed Order search response: {exc}"
                ) from exc

        if payment.status is ProviderPaymentStatus.SUCCEEDED:
            return await self._attach_captured_payment(payment)
        return payment

    def verify_webhook(
        self,
        *,
        body: bytes,
        signature: str,
        provider_event_id: str | None = None,
    ) -> VerifiedWebhookEvent:
        """Verify raw-body HMAC and parse only supported Razorpay events."""
        expected = (
            hmac.new(self._webhook_secret.encode("utf-8"), body, hashlib.sha256)
            .hexdigest()
            .encode("ascii")
        )
        try:
            supplied = signature.encode("ascii")
        except UnicodeEncodeError as exc:
            raise WebhookVerificationError(self.name, "X-Razorpay-Signature is not ASCII") from exc
        if not hmac.compare_digest(expected, supplied):
            raise WebhookVerificationError(self.name, "X-Razorpay-Signature does not match")
        if not provider_event_id:
            raise WebhookVerificationError(
                self.name,
                "X-Razorpay-Event-Id is required for idempotent delivery",
                reason_code="WEBHOOK_EVENT_ID_MISSING",
            )

        try:
            parsed = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WebhookVerificationError(
                self.name,
                "body is not valid JSON",
                reason_code="WEBHOOK_PAYLOAD_INVALID",
            ) from exc
        if not isinstance(parsed, dict):
            raise WebhookVerificationError(
                self.name,
                "body is not a JSON object",
                reason_code="WEBHOOK_PAYLOAD_INVALID",
            )

        event_name = parsed.get("event")
        if event_name not in {
            "payment.authorized",
            "payment.captured",
            "payment.failed",
            "order.paid",
        }:
            raise WebhookVerificationError(
                self.name,
                f"unsupported Razorpay event {event_name!r}",
                reason_code="WEBHOOK_PAYLOAD_INVALID",
            )

        try:
            evidence = self._webhook_evidence(parsed, str(event_name))
            occurred_at = parsed.get("created_at")
            occurred = (
                datetime.fromtimestamp(occurred_at, tz=timezone.utc)
                if isinstance(occurred_at, int) and not isinstance(occurred_at, bool)
                else None
            )
            return VerifiedWebhookEvent(
                provider=self.name,
                provider_event_id=provider_event_id,
                occurred_at=occurred,
                sequence=None,
                **evidence,
            )
        except (TypeError, ValueError) as exc:
            raise WebhookVerificationError(
                self.name,
                f"malformed signed Razorpay event: {exc}",
                reason_code="WEBHOOK_PAYLOAD_INVALID",
            ) from exc

    def _webhook_evidence(self, parsed: dict[str, Any], event_name: str) -> dict[str, Any]:
        payload = parsed.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("payload is missing")

        payment_wrapper = payload.get("payment")
        payment = payment_wrapper.get("entity") if isinstance(payment_wrapper, dict) else None
        if not isinstance(payment, dict):
            raise ValueError("payment entity is missing")

        payment_id = payment.get("id")
        order_id = payment.get("order_id")
        status = payment.get("status")
        currency = payment.get("currency")
        if not isinstance(payment_id, str) or not payment_id.startswith("pay_"):
            raise ValueError("payment id is malformed")
        if not isinstance(order_id, str) or not order_id.startswith("order_"):
            raise ValueError("payment order_id is malformed")
        if not isinstance(status, str) or not status:
            raise ValueError("payment status is missing")
        if not isinstance(currency, str) or len(currency) != 3:
            raise ValueError("payment currency is malformed")
        amount_inr = self._whole_rupees(payment.get("amount"), field="payment.amount")

        event_types = {
            "payment.authorized": WebhookEventType.PAYMENT_PENDING,
            "payment.captured": WebhookEventType.PAYMENT_SUCCEEDED,
            "payment.failed": WebhookEventType.PAYMENT_ATTEMPT_FAILED,
            "order.paid": WebhookEventType.PAYMENT_SUCCEEDED,
        }
        required_status = {
            "payment.authorized": "authorized",
            "payment.captured": "captured",
            "payment.failed": "failed",
            "order.paid": "captured",
        }[event_name]
        if status != required_status:
            raise ValueError(
                f"{event_name} carries payment status {status!r}, expected {required_status!r}"
            )
        if event_name in {"payment.captured", "order.paid"} and payment.get("captured") is not True:
            raise ValueError("success event does not carry captured=true")

        attempts: int | None = None
        if event_name == "order.paid":
            order_wrapper = payload.get("order")
            order = order_wrapper.get("entity") if isinstance(order_wrapper, dict) else None
            if not isinstance(order, dict):
                raise ValueError("order.paid has no order entity")
            if order.get("id") != order_id or order.get("status") != "paid":
                raise ValueError("order.paid entities disagree on Order identity or status")
            order_amount = self._whole_rupees(order.get("amount"), field="order.amount")
            if order_amount != amount_inr or order.get("currency") != currency:
                raise ValueError("order.paid entities disagree on amount or currency")
            attempts = self._non_negative_int(order.get("attempts"), field="order.attempts")

        return {
            "event_type": event_types[event_name],
            # Generic durable correlation remains the Order id.
            "provider_payment_id": order_id,
            "provider_order_id": order_id,
            "provider_transaction_id": payment_id,
            "amount_inr": amount_inr,
            "currency": currency,
            "provider_status": status,
            "provider_attempts": attempts,
        }


def from_environment(http_client: Any = None) -> RazorpayTestPaymentProvider:
    """Build from central environment/.env settings with redacted SecretStr values."""
    from apps.api.pactra.config import Settings

    settings = Settings()
    return RazorpayTestPaymentProvider(
        key_id=settings.razorpay_key_id,
        key_secret=settings.razorpay_key_secret.get_secret_value(),
        webhook_secret=settings.razorpay_webhook_secret.get_secret_value(),
        duplicate_receipt_rejection_enabled=(settings.razorpay_duplicate_receipt_rejection_enabled),
        http_client=http_client,
        connect_timeout_seconds=settings.razorpay_connect_timeout_seconds,
        read_timeout_seconds=settings.razorpay_read_timeout_seconds,
        write_timeout_seconds=settings.razorpay_write_timeout_seconds,
        pool_timeout_seconds=settings.razorpay_pool_timeout_seconds,
        overall_timeout_seconds=settings.razorpay_overall_timeout_seconds,
    )
