"""The payment state machine, including property-based invariants.

Two of the webhook requirements — "a delayed webhook must not regress terminal
state" and "an out-of-order webhook must not produce an illegal transition" —
are really claims about this table. Testing them here as properties means they
hold for every state pair, not only the pairs a handwritten webhook test
happened to exercise.
"""

import pytest
from hypothesis import given
from hypothesis import strategies as st
from packages.schemas.payment import (
    TERMINAL_PAYMENT_STATES,
    PaymentIntentState,
    ProviderPaymentStatus,
    WebhookEventType,
    provider_status_to_state,
    webhook_type_to_state,
)
from services.payment_executor.state_machine import (
    ALLOWED_PAYMENT_TRANSITIONS,
    IllegalPaymentTransition,
    assert_payment_transition,
    can_transition,
    is_terminal,
)

STATES = list(PaymentIntentState)
states = st.sampled_from(STATES)


# --------------------------------------------------------------------------- #
# Structural completeness
# --------------------------------------------------------------------------- #
def test_every_state_has_a_transition_rule():
    """A state missing from the table would silently permit nothing — or worse,
    be read as 'undefined' by a future edit. Absence must be a test failure."""
    assert set(ALLOWED_PAYMENT_TRANSITIONS) == set(STATES)


def test_no_transition_targets_an_unknown_state():
    for targets in ALLOWED_PAYMENT_TRANSITIONS.values():
        assert targets <= set(STATES)


def test_the_state_set_is_exactly_the_specified_one():
    """No extra states were invented."""
    assert {s.value for s in STATES} == {
        "CREATED",
        "QUEUED",
        "PROCESSING",
        "PROVIDER_PENDING",
        "SUCCEEDED",
        "FAILED_RETRYABLE",
        "FAILED_TERMINAL",
        "CANCELLED",
    }


# --------------------------------------------------------------------------- #
# Terminal states are absorbing — the delayed-webhook guarantee
# --------------------------------------------------------------------------- #
@given(current=states, target=states)
def test_terminal_states_never_transition(current, target):
    """DELAYED WEBHOOK -> CANNOT REGRESS TERMINAL PAYMENT STATE.

    Property-based, so it holds for every (terminal, anything) pair rather than
    for the one or two a handwritten test would pick.
    """
    if current in TERMINAL_PAYMENT_STATES:
        assert not can_transition(current, target)
        with pytest.raises(IllegalPaymentTransition):
            assert_payment_transition(current, target)


def test_terminal_set_matches_the_transition_table():
    """The two encodings of 'terminal' cannot drift apart."""
    from_table = {s for s, targets in ALLOWED_PAYMENT_TRANSITIONS.items() if not targets}
    assert from_table == set(TERMINAL_PAYMENT_STATES)
    for state in STATES:
        assert is_terminal(state) == (state in from_table)


# --------------------------------------------------------------------------- #
# Illegal transitions always raise — the out-of-order webhook guarantee
# --------------------------------------------------------------------------- #
@given(current=states, target=states)
def test_assert_agrees_with_can_transition(current, target):
    """OUT-OF-ORDER WEBHOOK -> NO ILLEGAL STATE TRANSITION.

    The guard and the predicate must never disagree; if they could, a caller
    checking one and relying on the other would have a hole.
    """
    if can_transition(current, target):
        assert_payment_transition(current, target)
    else:
        with pytest.raises(IllegalPaymentTransition):
            assert_payment_transition(current, target)


@given(state=states)
def test_no_state_transitions_to_itself(state):
    """Self-transitions are excluded so a repeated event is always visibly a
    no-op rather than an apparently successful re-application."""
    assert not can_transition(state, state)


# --------------------------------------------------------------------------- #
# Reachability
# --------------------------------------------------------------------------- #
def test_success_is_reachable_from_every_non_terminal_state():
    """A payment must never get stuck somewhere it can neither settle nor fail."""
    reachable_from = {}
    for start in STATES:
        seen, stack = set(), [start]
        while stack:
            node = stack.pop()
            for nxt in ALLOWED_PAYMENT_TRANSITIONS[node]:
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        reachable_from[start] = seen

    for state in STATES:
        if state in TERMINAL_PAYMENT_STATES:
            continue
        assert reachable_from[state] & TERMINAL_PAYMENT_STATES, (
            f"{state.value} cannot reach any terminal state — a payment could hang forever"
        )


def test_the_uncertain_state_can_always_be_resolved():
    """PROVIDER_PENDING must converge on SUCCEEDED or FAILED_TERMINAL rather
    than remaining permanently ambiguous."""
    targets = ALLOWED_PAYMENT_TRANSITIONS[PaymentIntentState.PROVIDER_PENDING]
    assert PaymentIntentState.SUCCEEDED in targets
    assert PaymentIntentState.FAILED_TERMINAL in targets


def test_uncertainty_becomes_retryable_only_through_reconciliation():
    """FAILED_RETRYABLE is reachable from PROVIDER_PENDING — but the only code
    path that takes it is reconciliation establishing the provider holds no
    payment. Nothing time-based promotes an uncertain payment to retryable."""
    assert can_transition(PaymentIntentState.PROVIDER_PENDING, PaymentIntentState.FAILED_RETRYABLE)
    # And a retryable payment goes back through the queue, never straight to
    # PROCESSING, so it is always re-dispatched by a claimed outbox event.
    assert can_transition(PaymentIntentState.FAILED_RETRYABLE, PaymentIntentState.QUEUED)
    assert not can_transition(PaymentIntentState.FAILED_RETRYABLE, PaymentIntentState.PROCESSING)


# --------------------------------------------------------------------------- #
# Provider / webhook vocabulary translation
# --------------------------------------------------------------------------- #
@given(status=st.sampled_from(list(ProviderPaymentStatus)))
def test_every_provider_status_translates(status):
    """A provider status with no mapping would raise at runtime in the executor."""
    assert isinstance(provider_status_to_state(status), PaymentIntentState)


@given(event_type=st.sampled_from(list(WebhookEventType)))
def test_every_webhook_type_translates(event_type):
    assert isinstance(webhook_type_to_state(event_type), PaymentIntentState)


def test_an_unverified_provider_string_cannot_name_an_internal_state():
    """Provider vocabulary is translated, never adopted.

    A hostile provider returning the literal string "SUCCEEDED" for a status
    PACTRA does not recognise gets a ValueError at the enum boundary, not a
    state transition.
    """
    with pytest.raises(ValueError):
        ProviderPaymentStatus("TOTALLY_SUCCEEDED_TRUST_ME")
    with pytest.raises(ValueError):
        WebhookEventType("payment.definitely_succeeded")
