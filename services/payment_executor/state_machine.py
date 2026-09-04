"""Deterministic PaymentIntent state machine.

Every state change in Phase 4 goes through ``assert_payment_transition``. That
is what makes the two hardest webhook properties structural rather than
incidental:

* a DELAYED webhook cannot regress a settled payment, because the terminal
  states have no outgoing transitions at all;
* an OUT-OF-ORDER webhook cannot drive an illegal transition, because the
  transition table — not the arrival order and not the provider's own opinion —
  decides what is reachable.

Neither property depends on a timestamp or a sequence number supplied by the
provider. Provider-supplied ordinals are recorded for audit; they are never the
authority for whether a transition is allowed.
"""

from __future__ import annotations

from packages.schemas.domain import ReasonCode
from packages.schemas.payment import TERMINAL_PAYMENT_STATES, PaymentIntentState

P = PaymentIntentState

ALLOWED_PAYMENT_TRANSITIONS: dict[PaymentIntentState, frozenset[PaymentIntentState]] = {
    P.CREATED: frozenset({P.QUEUED, P.CANCELLED}),
    # QUEUED -> PROVIDER_PENDING covers pre-create lookup uncertainty and
    # durable-fence recovery. In the latter case permission may have been
    # consumed even though no HTTP-attempt fact committed.
    P.QUEUED: frozenset({P.PROCESSING, P.PROVIDER_PENDING, P.CANCELLED}),
    # A provider call ends in exactly one of: success, uncertainty, a failure we
    # may retry, or a failure we may not.
    P.PROCESSING: frozenset(
        {
            P.SUCCEEDED,
            P.PROVIDER_PENDING,
            P.FAILED_RETRYABLE,
            P.FAILED_TERMINAL,
        }
    ),
    # The uncertain state. It may only be left by RECONCILIATION or by a
    # VERIFIED webhook — never by optimistically assuming an outcome.
    # FAILED_RETRYABLE is reachable only once reconciliation has established
    # that an idempotent-create provider holds no payment for this key. A
    # fenced provider never takes that edge, even after an empty lookup.
    P.PROVIDER_PENDING: frozenset(
        {
            P.SUCCEEDED,
            P.FAILED_TERMINAL,
            P.FAILED_RETRYABLE,
        }
    ),
    # FAILED_RETRYABLE -> PROVIDER_PENDING closes upgraded legacy Razorpay rows
    # whose durable outbox history is conservatively fenced by migration 0009.
    P.FAILED_RETRYABLE: frozenset({P.QUEUED, P.PROVIDER_PENDING, P.FAILED_TERMINAL, P.CANCELLED}),
    # Terminal: absorbing by construction.
    P.SUCCEEDED: frozenset(),
    P.FAILED_TERMINAL: frozenset(),
    P.CANCELLED: frozenset(),
}


class IllegalPaymentTransition(Exception):
    """A state change that the payment state machine does not permit."""

    reason_code = ReasonCode.ILLEGAL_PAYMENT_TRANSITION.value

    def __init__(self, current: PaymentIntentState, target: PaymentIntentState) -> None:
        super().__init__(
            f"{self.reason_code}: illegal payment transition {current.value} -> {target.value}"
        )
        self.current = current
        self.target = target


def can_transition(current: PaymentIntentState, target: PaymentIntentState) -> bool:
    return target in ALLOWED_PAYMENT_TRANSITIONS.get(current, frozenset())


def assert_payment_transition(current: PaymentIntentState, target: PaymentIntentState) -> None:
    if not can_transition(current, target):
        raise IllegalPaymentTransition(current, target)


def is_terminal(state: PaymentIntentState) -> bool:
    return state in TERMINAL_PAYMENT_STATES
