"""Deterministic anomaly baselines. Refuses to invent one.

THE ONE RULE
------------
An anomaly is a deviation FROM SOMETHING. Where there is no something, this
module returns ``MerchantHistory(available=False)`` and every anomaly factor
downstream reports ``INSUFFICIENT_HISTORY`` and contributes exactly nothing. It
never substitutes a global default, a prior, a smoothed estimate, or a zero.

That matters more than it sounds. "This purchase is 3.1x the median" computed
from two prior observations is a number with the shape of evidence and none of
the substance, and it would be indistinguishable in a report from the same
sentence backed by five hundred. So the gate is explicit
(``RiskConfig.min_history_observations``), the observation count travels in
``DataQuality``, and the explanation says which case it was.

WHAT PACTRA CAN AND CANNOT BASELINE — STATED, NOT WORKED AROUND
---------------------------------------------------------------
**Cannot: anything per-user.** There is no user identity anywhere in the data
model. ``missions`` has no owner column, no account, no session principal; a
mission is anonymous. So there is no such thing as "this user's typical spend",
"this user's recent velocity", or "unusual for this user" in PACTRA today, and
this module does not manufacture one. Every candidate user-scoped feature in the
Phase 7 brief is therefore absent rather than approximated. Adding it means
adding a user identity to the domain first.

**Can: per-merchant.** ``authorizations.bound_merchant_id`` and
``bound_amount_inr`` are server-written records of transactions actually
approved against an AUTHENTICATED merchant identity. That is a real, defensible
population, and it is the one this module uses.

WHY AUTHORIZATIONS AND NOT SETTLED PAYMENTS
-------------------------------------------
A settled payment is the narrower and more tempting population — it is
"transactions that really happened". But most missions legitimately stop at
approval, so a payment-only baseline would sit below the observation gate almost
always and the anomaly layer would be permanently dark. An authorization is
still a server-issued commitment to an exact amount with an exact merchant, and
there are enough of them for a median to mean something. The failure-ratio
feature, which is genuinely about payment outcomes, does use payment intents.

WHY THE MEDIAN
--------------
The mean is moved by the single largest prior transaction, which is exactly the
observation an attacker would like to contribute. The median needs half the
population to move.
"""

from __future__ import annotations

import statistics
import uuid
from dataclasses import dataclass

from apps.api.db.models import AuthorizationRow, PaymentIntentRow
from packages.schemas.payment import PaymentIntentState
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

#: Payment states that count as a settled failure for the failure ratio.
#: ``FAILED_RETRYABLE`` is excluded on purpose: it is a payment still in play,
#: not an outcome, and counting an in-flight retry as a failure would make a
#: transient network blip look like a merchant with a bad record.
FAILED_STATES: frozenset[str] = frozenset(
    {
        PaymentIntentState.FAILED_TERMINAL.value,
    }
)

SETTLED_STATES: frozenset[str] = frozenset(
    {
        PaymentIntentState.SUCCEEDED.value,
    }
)

#: Upper bound on prior rows pulled for one baseline. A risk assessment must be
#: cheap; an unbounded scan over the history of a busy merchant is not. The most
#: recent window is the relevant one anyway — a two-year-old amount says little
#: about today's typical transaction.
HISTORY_WINDOW = 200


@dataclass(frozen=True)
class MerchantHistory:
    """Prior observations for one authenticated merchant, or the absence of any.

    ``available`` is the gate: False means "not enough to baseline", and every
    consumer must treat the medians as absent rather than as zero. The counts
    are carried even when unavailable, because "we had 2 observations and needed
    5" is a more useful thing to report than "no history".
    """

    merchant_id: str
    #: Prior authorized amounts, excluding the mission being assessed.
    amount_observations: int
    median_amount_inr: float | None
    #: Prior settled payment outcomes, excluding the mission being assessed.
    settled_payments: int
    failed_payments: int
    #: True when ``amount_observations`` met the configured minimum.
    available: bool
    #: True when there were no prior observations of ANY kind. Distinct from
    #: ``not available``: three observations is not a cold start, it is a thin
    #: one, and the two deserve different sentences in an explanation.
    cold_start: bool

    @property
    def payment_observations(self) -> int:
        return self.settled_payments + self.failed_payments

    @property
    def failure_ratio(self) -> float | None:
        """Failed / (failed + settled), or ``None`` when nothing settled.

        Gating on the OBSERVATION COUNT is the caller's job — this property only
        refuses to divide by zero. A ratio computed from one payment is
        arithmetically fine and epistemically worthless, which is why
        ``RiskConfig.min_merchant_payment_history`` exists upstream of it.
        """
        total = self.payment_observations
        if total == 0:
            return None
        return self.failed_payments / total

    def amount_ratio(self, amount_inr: int) -> float | None:
        """How many times the historical median this amount is.

        ``None`` when no baseline is available, which is what makes the anomaly
        factor skip rather than score. A zero or negative median cannot occur —
        ``BoundTransaction.amount_inr`` is ``ge=1`` — but it is guarded anyway,
        because a division that only fails on impossible data still fails.
        """
        if not self.available or self.median_amount_inr is None:
            return None
        if self.median_amount_inr <= 0:
            return None
        return amount_inr / self.median_amount_inr


def empty_history(merchant_id: str) -> MerchantHistory:
    """The honest answer when there is no counterparty to have history with."""
    return MerchantHistory(
        merchant_id=merchant_id,
        amount_observations=0,
        median_amount_inr=None,
        settled_payments=0,
        failed_payments=0,
        available=False,
        cold_start=True,
    )


async def load_merchant_history(
    session: AsyncSession,
    *,
    merchant_id: str,
    exclude_mission_id: uuid.UUID,
    min_observations: int,
) -> MerchantHistory:
    """Read one merchant's prior record. SELECT only — nothing is written.

    ``exclude_mission_id`` is not an optimisation. Including the mission under
    assessment would let a transaction contribute to the baseline it is being
    compared against, which pulls the median toward the very value in question
    and shrinks every deviation. A single-transaction merchant would then always
    look perfectly typical.
    """
    amount_rows = await session.execute(
        select(AuthorizationRow.bound_amount_inr)
        .where(
            AuthorizationRow.bound_merchant_id == merchant_id,
            AuthorizationRow.mission_id != exclude_mission_id,
        )
        .order_by(AuthorizationRow.issued_at.desc())
        .limit(HISTORY_WINDOW)
    )
    amounts = [int(value) for value in amount_rows.scalars().all()]

    payment_rows = await session.execute(
        select(PaymentIntentRow.state)
        .where(
            PaymentIntentRow.merchant_id == merchant_id,
            PaymentIntentRow.mission_id != exclude_mission_id,
        )
        .order_by(PaymentIntentRow.created_at.desc())
        .limit(HISTORY_WINDOW)
    )
    states = [str(value) for value in payment_rows.scalars().all()]

    settled = sum(state in SETTLED_STATES for state in states)
    failed = sum(state in FAILED_STATES for state in states)

    available = len(amounts) >= min_observations
    return MerchantHistory(
        merchant_id=merchant_id,
        amount_observations=len(amounts),
        # Computed ONLY when the gate passed. Computing it anyway "for
        # information" is how an ungated median ends up in a report.
        median_amount_inr=float(statistics.median(amounts)) if available else None,
        settled_payments=settled,
        failed_payments=failed,
        available=available,
        cold_start=not amounts and not states,
    )
