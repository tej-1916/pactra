"""``PaymentRailAdapter`` — the family PACTRA already had, named.

THIS MODULE ADDS NO ABSTRACTION. IT DOCUMENTS ONE.
--------------------------------------------------
PACTRA's payment-rail adapter boundary is
``services.payment_executor.providers.base.PaymentProvider``, delivered in
Phase 4 and covered by the reliability suite. Phase 8 does not rename it, wrap
it, or route it through the translating adapter registry. A rename would churn a
working abstraction for naming aesthetics; a wrapper would add a layer between
the executor and the rail whose only content is a different word.

WHY A RAIL IS NOT A TRANSLATING ADAPTER
    Every other family in this package is a PURE FUNCTION: bytes in, canonical
    candidate out, no session, no I/O, no state. A payment rail is the opposite
    — it is the one component in PACTRA that MOVES MONEY. Its methods are
    ``async``, they perform network I/O, and reaching them requires the
    ``payment.execute`` capability held by exactly one principal.

    Registering a rail in the translating registry would put an execution
    adapter among pure translations, which is precisely the cross-family
    confusion this phase corrects. ``AdapterRegistry.register`` therefore
    REFUSES ``AdapterFamily.PAYMENT_RAIL`` with that reason attached.

THE CONTRACT, RESTATED SO THE FAMILY DEFINITION IS COMPLETE
    ``create_payment``    idempotency-keyed creation, or the existing payment
    ``get_payment``       lookup by provider id OR by idempotency key — the only
                          handle left after a create whose response was lost
    ``verify_webhook``    MAC over the RAW bytes, constant-time, before parsing

    And the error taxonomy that carries the reliability guarantee:
    ``ProviderTimeout`` is UNCERTAINTY, not failure; ``ProviderTransientError``
    means no payment was created; ``ProviderTerminalError`` means a definitive
    refusal; ``ProviderPaymentMismatch`` means a 200 response that does not
    describe this intent and must never be linked or settled.

WHAT ARRIVES FROM A RAIL IS UNTRUSTED
    Provider responses are untrusted input even at HTTP 200, and the executor
    validates provider, amount, currency and idempotency key against the durable
    intent BEFORE linking anything. That is the same rule this package applies to
    a protocol payload: a response may report state, never redefine the
    transaction.
"""

from __future__ import annotations

from services.adapters.models import AdapterFamily, SupportStatus
from services.payment_executor.providers.base import PaymentProvider
from services.payment_executor.registry import registered_provider_names

FAMILY = AdapterFamily.PAYMENT_RAIL

#: The rail boundary itself. Re-exported so a reader of this package can follow
#: the family to its contract without being told to go and look elsewhere.
PAYMENT_RAIL_PROTOCOL = PaymentProvider

#: Where the server-owned name -> adapter resolution actually lives. Named as
#: data so the support matrix and the CLI can point at one place.
RAIL_REGISTRY_MODULE = "services.payment_executor.registry"

#: What PACTRA claims about each rail. ``fake`` is a TEST DOUBLE whose webhook
#: secret is a literal in the source tree — a deployment accepting its
#: signatures would accept anybody's — so it is registered outside production
#: only and is marked NOT_APPLICABLE rather than given a support status it would
#: not deserve.
RAIL_STATUS: dict[str, SupportStatus] = {
    "razorpay_test": SupportStatus.PARTIAL,
    "fake": SupportStatus.NOT_APPLICABLE,
}


def describe_payment_rails(
    *, app_env: str = "development"
) -> tuple[tuple[str, SupportStatus], ...]:
    """The rails this deployment resolves, with PACTRA's claim about each.

    READ-ONLY, and it constructs nothing. Resolving an adapter needs credentials
    and is the payment executor's business; listing names is not. Reading the
    names from ``services.payment_executor.registry`` rather than restating them
    keeps one source of truth, so a rail added there cannot go missing here.
    """
    return tuple(
        (name, RAIL_STATUS.get(name, SupportStatus.NOT_APPLICABLE))
        for name in registered_provider_names(app_env=app_env)
    )


__all__ = [
    "FAMILY",
    "PAYMENT_RAIL_PROTOCOL",
    "RAIL_REGISTRY_MODULE",
    "RAIL_STATUS",
    "describe_payment_rails",
]
