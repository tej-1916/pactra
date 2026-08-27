"""Explicit, auditable mission state machine.

Transitions are enumerated deterministically. Any attempt to move between two
states that is not explicitly permitted raises IllegalTransition. This keeps
mission progression easy to reason about and prevents "hidden agent magic".
"""

from __future__ import annotations

from packages.schemas.domain import MissionState

S = MissionState

ALLOWED_TRANSITIONS: dict[MissionState, set[MissionState]] = {
    S.CREATED: {S.INTENT_PARSED, S.CANCELLED},
    S.INTENT_PARSED: {S.DISCOVERING, S.CANCELLED},
    S.DISCOVERING: {S.OFFERS_RECEIVED, S.CANCELLED},
    S.OFFERS_RECEIVED: {S.OFFERS_NORMALIZED, S.CANCELLED},
    S.OFFERS_NORMALIZED: {S.RANKED, S.CANCELLED},
    S.RANKED: {S.POLICY_CHECKED, S.CANCELLED},
    # AUTHORIZED/PAYMENT_* transitions are defined for later phases (transaction
    # binding, authorization, payment) but are not exercised yet.
    S.POLICY_CHECKED: {S.AWAITING_APPROVAL, S.AUTHORIZED, S.CANCELLED},
    S.AWAITING_APPROVAL: {S.AUTHORIZED, S.CANCELLED},
    S.AUTHORIZED: {S.PAYMENT_PENDING, S.CANCELLED},
    S.PAYMENT_PENDING: {S.PAYMENT_SUCCEEDED, S.PAYMENT_FAILED},
    S.PAYMENT_SUCCEEDED: {S.COMPLETED},
    S.PAYMENT_FAILED: {S.CANCELLED, S.PAYMENT_PENDING},
    S.COMPLETED: set(),
    S.CANCELLED: set(),
}


class IllegalTransition(Exception):
    def __init__(self, current: MissionState, target: MissionState) -> None:
        super().__init__(f"Illegal mission transition: {current.value} -> {target.value}")
        self.current = current
        self.target = target


def can_transition(current: MissionState, target: MissionState) -> bool:
    return target in ALLOWED_TRANSITIONS.get(current, set())


def assert_transition(current: MissionState, target: MissionState) -> None:
    if not can_transition(current, target):
        raise IllegalTransition(current, target)
