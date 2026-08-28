"""The anomaly layer must refuse to invent a baseline it does not have."""

from __future__ import annotations

import uuid

import pytest
from apps.api.db.models import Mission
from packages.schemas.capability import security_kernel_capabilities
from packages.schemas.payment import PaymentIntentState
from services.risk_engine.anomaly import (
    HISTORY_WINDOW,
    MerchantHistory,
    empty_history,
    load_merchant_history,
)
from services.security_kernel.authorization import generate_nonce, issue_authorization
from tests.conftest import approved_transaction

# No module-level asyncio mark: this file mixes async database tests with pure
# ones, and `asyncio_mode = "auto"` already collects the async ones.
KERNEL = security_kernel_capabilities()
MIN = 5


async def _authorize(session, *, merchant_id: str, amount: int, index: int) -> uuid.UUID:
    """A real authorization on a real mission. Never an inserted row."""
    mission = Mission(id=uuid.uuid4(), quantity=1, state="POLICY_CHECKED")
    session.add(mission)
    await session.flush()
    await issue_authorization(
        session,
        capabilities=KERNEL,
        mission_id=mission.id,
        transaction=approved_transaction(
            merchant_id=merchant_id,
            product_id=f"p-{index}",
            amount_inr=amount,
            nonce=generate_nonce(),
        ),
    )
    await session.flush()
    return mission.id


# --------------------------------------------------------------------------- #
# The gate
# --------------------------------------------------------------------------- #
async def test_no_history_is_reported_as_cold_start(session):
    history = await load_merchant_history(
        session, merchant_id="nobody", exclude_mission_id=uuid.uuid4(), min_observations=MIN
    )
    assert history.cold_start is True
    assert history.available is False
    assert history.median_amount_inr is None
    assert history.amount_ratio(5000) is None


async def test_thin_history_is_not_a_baseline_and_is_not_cold_start(session):
    for index, amount in enumerate([1000, 1100]):
        await _authorize(session, merchant_id="thin", amount=amount, index=index)
    await session.commit()

    history = await load_merchant_history(
        session, merchant_id="thin", exclude_mission_id=uuid.uuid4(), min_observations=MIN
    )
    assert history.amount_observations == 2
    assert history.available is False
    assert history.cold_start is False
    # The distinction that matters: no median is computed at all, not a median
    # from two points.
    assert history.median_amount_inr is None
    assert history.amount_ratio(9999) is None


async def test_sufficient_history_produces_a_median(session):
    for index, amount in enumerate([1000, 1000, 1000, 5000, 1000, 1000]):
        await _authorize(session, merchant_id="steady", amount=amount, index=index)
    await session.commit()

    history = await load_merchant_history(
        session, merchant_id="steady", exclude_mission_id=uuid.uuid4(), min_observations=MIN
    )
    assert history.available is True
    # The median, not the mean: one large prior observation must not move it.
    assert history.median_amount_inr == pytest.approx(1000.0)
    assert history.amount_ratio(3000) == pytest.approx(3.0)


async def test_the_median_resists_a_single_large_observation(session):
    """The mean would be moved by exactly the observation an attacker contributes."""
    amounts = [1000] * 5 + [1_000_000]
    for index, amount in enumerate(amounts):
        await _authorize(session, merchant_id="skewed", amount=amount, index=index)
    await session.commit()

    history = await load_merchant_history(
        session, merchant_id="skewed", exclude_mission_id=uuid.uuid4(), min_observations=MIN
    )
    mean = sum(amounts) / len(amounts)
    assert history.median_amount_inr == pytest.approx(1000.0)
    assert history.median_amount_inr < mean / 100


# --------------------------------------------------------------------------- #
# Scope
# --------------------------------------------------------------------------- #
async def test_the_mission_under_assessment_is_excluded_from_its_own_baseline(session):
    """Otherwise a transaction pulls the median toward itself and looks typical."""
    for index in range(6):
        await _authorize(session, merchant_id="scoped", amount=1000, index=index)
    current = await _authorize(session, merchant_id="scoped", amount=9000, index=99)
    await session.commit()

    history = await load_merchant_history(
        session, merchant_id="scoped", exclude_mission_id=current, min_observations=MIN
    )
    assert history.amount_observations == 6
    assert history.median_amount_inr == pytest.approx(1000.0)
    assert history.amount_ratio(9000) == pytest.approx(9.0)


async def test_history_is_scoped_to_one_merchant(session):
    for index in range(6):
        await _authorize(session, merchant_id="alpha", amount=1000, index=index)
    for index in range(6):
        await _authorize(session, merchant_id="beta", amount=8000, index=100 + index)
    await session.commit()

    alpha = await load_merchant_history(
        session, merchant_id="alpha", exclude_mission_id=uuid.uuid4(), min_observations=MIN
    )
    beta = await load_merchant_history(
        session, merchant_id="beta", exclude_mission_id=uuid.uuid4(), min_observations=MIN
    )
    assert alpha.median_amount_inr == pytest.approx(1000.0)
    assert beta.median_amount_inr == pytest.approx(8000.0)


async def test_the_history_window_is_bounded(session):
    """A risk assessment must be cheap; an unbounded scan is not."""
    assert HISTORY_WINDOW > 0
    assert HISTORY_WINDOW <= 1000


# --------------------------------------------------------------------------- #
# Failure ratio
# --------------------------------------------------------------------------- #
def test_failure_ratio_is_none_when_nothing_settled():
    history = empty_history("nobody")
    assert history.failure_ratio is None
    assert history.payment_observations == 0


def test_failure_ratio_excludes_in_flight_retries():
    """FAILED_RETRYABLE is a payment still in play, not an outcome.

    Counting a transient blip as a merchant failure would give a healthy
    merchant a bad record for a network problem.
    """
    from services.risk_engine.anomaly import FAILED_STATES, SETTLED_STATES

    assert PaymentIntentState.FAILED_RETRYABLE.value not in FAILED_STATES
    assert PaymentIntentState.FAILED_TERMINAL.value in FAILED_STATES
    assert PaymentIntentState.SUCCEEDED.value in SETTLED_STATES
    assert FAILED_STATES.isdisjoint(SETTLED_STATES)


def test_failure_ratio_is_computed_from_settled_outcomes():
    history = MerchantHistory(
        merchant_id="m",
        amount_observations=10,
        median_amount_inr=1000.0,
        settled_payments=3,
        failed_payments=1,
        available=True,
        cold_start=False,
    )
    assert history.payment_observations == 4
    assert history.failure_ratio == pytest.approx(0.25)


def test_a_zero_median_never_divides():
    """Unreachable through the kernel; guarded anyway."""
    history = MerchantHistory(
        merchant_id="m",
        amount_observations=10,
        median_amount_inr=0.0,
        settled_payments=0,
        failed_payments=0,
        available=True,
        cold_start=False,
    )
    assert history.amount_ratio(500) is None


async def test_loading_history_writes_nothing(session):
    await _authorize(session, merchant_id="ro", amount=1000, index=0)
    await session.commit()
    await load_merchant_history(
        session, merchant_id="ro", exclude_mission_id=uuid.uuid4(), min_observations=MIN
    )
    assert list(session.new) == []
    assert list(session.dirty) == []
    assert list(session.deleted) == []
