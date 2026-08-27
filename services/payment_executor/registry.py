"""Server-owned resolution of provider NAME -> provider ADAPTER.

The name that reaches this module comes from untrusted places — a URL path
segment on a webhook, a column on a stored intent — so the mapping itself must
be server-owned, the same rule the capability registry follows. An unknown name
resolves to nothing; it never falls back to a default adapter, because a
webhook delivered to an unrecognised path must not be verified against whatever
secret happened to be configured.

``FakePaymentProvider`` is registered only outside production. It is a test
double whose webhook secret is a literal in the source tree, so a deployment
that accepted its signatures would accept anybody's.
"""

from __future__ import annotations

from functools import lru_cache

from services.payment_executor.providers.base import PaymentProvider
from services.payment_executor.providers.fake import FakePaymentProvider
from services.payment_executor.providers.razorpay import (
    PROVIDER_NAME as RAZORPAY_NAME,
)
from services.payment_executor.providers.razorpay import from_environment

#: The HTTP header each provider signs its webhooks with. Kept here rather than
#: guessed at the route, so adding a provider cannot silently inherit another
#: provider's header name.
WEBHOOK_SIGNATURE_HEADERS: dict[str, str] = {
    "fake": "x-fake-signature",
    RAZORPAY_NAME: "x-razorpay-signature",
}


class UnknownProvider(Exception):
    """No adapter is registered under this name."""

    reason_code = "UNKNOWN_PAYMENT_PROVIDER"

    def __init__(self, name: str) -> None:
        super().__init__(f"{self.reason_code}: no payment provider named {name!r}")
        self.name = name


class ProviderUnavailable(Exception):
    """The adapter is registered but cannot be constructed here.

    Almost always a missing credential. Surfaced as its own type so a caller can
    tell "PACTRA does not know this provider" from "PACTRA knows it but this
    deployment is not configured for it" — two different operational problems.
    """

    reason_code = "PAYMENT_PROVIDER_UNAVAILABLE"

    def __init__(self, name: str, detail: str) -> None:
        super().__init__(f"{self.reason_code}: {detail}")
        self.name = name
        self.detail = detail


def registered_provider_names(*, app_env: str) -> tuple[str, ...]:
    if app_env == "production":
        return (RAZORPAY_NAME,)
    return ("fake", RAZORPAY_NAME)


@lru_cache
def _fake() -> FakePaymentProvider:
    """One instance per process: the fake's payment store IS its state, and a
    fresh instance per request would forget every payment it had created."""
    return FakePaymentProvider()


def provider_for(name: str, *, app_env: str = "development") -> PaymentProvider:
    """Resolve an adapter, or raise. Never returns a default."""
    if name not in registered_provider_names(app_env=app_env):
        raise UnknownProvider(name)

    if name == "fake":
        return _fake()

    try:
        return from_environment()
    except Exception as exc:  # noqa: BLE001 - reported, never swallowed
        # A missing RAZORPAY_* secret lands here. Deliberately not defaulted:
        # a fallback secret in source is a committed credential.
        raise ProviderUnavailable(name, f"{type(exc).__name__}: {exc}") from exc


def signature_header_for(name: str) -> str:
    header = WEBHOOK_SIGNATURE_HEADERS.get(name)
    if header is None:
        raise UnknownProvider(name)
    return header
