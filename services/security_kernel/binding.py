"""Transaction binding — turning an approved offer into a digest commitment.

This is the bridge between the kernel's provenance-coupled offer representation
and the flat, canonical ``BoundTransaction`` that an authorization commits to.

Two rules govern what goes into the binding:

* **Identity comes from the transport, never the payload.** ``merchant_id`` is
  taken from ``offer.merchant_id`` — the identity the transport authenticated —
  never from ``claimed_merchant_id``. Binding to a self-asserted identity would
  let a spoofing merchant bind an authorization to the name it was impersonating.
* **The amount comes from the policy decision, not the offer.** The decision's
  ``requested_amount`` is the quantity-multiplied total the policy engine
  actually adjudicated. Binding the unit price instead would leave an
  authorization that says nothing about how many units were approved.

Verification is a pure comparison of digests, so it is trivially auditable: an
authorization is usable only against a transaction that hashes to exactly the
digest recorded at approval time.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from apps.api.db.models import Offer
from packages.schemas.domain import PolicyDecision, PolicyOutcome, ReasonCode, as_utc
from packages.schemas.invariants import InvariantViolation, require
from packages.schemas.kernel import ProvenancedOffer
from packages.schemas.transaction import BoundTransaction, OfferCandidate, compute_offer_version
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Policy outcomes that may produce an authorization at all. A DENY decision
# never yields a bound transaction: NO VALID AUTHORIZATION -> NO PAYMENT.
AUTHORIZABLE_OUTCOMES = frozenset({PolicyOutcome.ALLOW, PolicyOutcome.REQUIRE_APPROVAL})

# Stable invariants carried by a bind-time refusal. Unlike the reason code,
# which says what a caller may branch on, these identify the exact internal
# rule that failed.
OFFER_VERSION_INVARIANT = "binding.selected_offer_version_matches_authoritative_record"
OFFER_VALID_INVARIANT = "binding.offer_is_valid"


class BindRefusedOfferChanged(Exception):
    """The selected offer no longer matches the bind-time structured record.

    One reason code, several invariants. Everything that can change about the
    authoritative offer row between selection and bind — it vanished, its
    content drifted, or ranking rejected it — is the same fact to a caller: the
    offer it chose is not the offer the server would bind, so no authorization
    exists. Branching logic reads ``reason_code``; ``invariant_id`` names the
    precise rule for operators and audit without widening that contract.
    """

    reason_code = ReasonCode.BIND_REFUSED_OFFER_CHANGED.value

    def __init__(
        self,
        *,
        mission_id: uuid.UUID,
        offer_id: uuid.UUID,
        detail: str,
        invariant_id: str = OFFER_VERSION_INVARIANT,
    ) -> None:
        super().__init__(f"{self.reason_code}: {detail}")
        self.mission_id = mission_id
        self.offer_id = offer_id
        self.detail = detail
        self.invariant_id = invariant_id


def _build_bound_transaction_from_values(
    *,
    offer_id: uuid.UUID,
    offer_valid: bool,
    merchant_id: str,
    product_id: str,
    unit_amount_inr: int,
    currency: str,
    offer_version: str,
    decision: PolicyDecision,
    quantity: int,
    nonce: str,
    expires_at: datetime,
) -> BoundTransaction:
    """Apply the common BIND invariants to provenance-coupled or stored data."""
    require(
        decision.decision in AUTHORIZABLE_OUTCOMES,
        "binding.decision_is_authorizable",
        f"cannot bind a transaction for a {decision.decision.value} decision",
    )
    require(
        offer_valid,
        OFFER_VALID_INVARIANT,
        f"offer {offer_id} was rejected and cannot be bound",
    )
    require(
        decision.selected_offer_id == offer_id,
        "binding.offer_matches_decision",
        f"decision selected {decision.selected_offer_id}, not offer {offer_id}",
    )
    amount = decision.requested_amount
    if amount is None:
        # Raised directly rather than via require() so the type checker narrows
        # `amount` here. Never an `assert`: assertions vanish under `python -O`.
        raise InvariantViolation(
            "binding.decision_has_amount",
            "an authorizable decision must carry the adjudicated amount",
        )
    require(
        amount == unit_amount_inr * quantity,
        "binding.amount_matches_offer_and_quantity",
        f"decision amount {amount} != unit {unit_amount_inr} x qty {quantity}",
    )

    return BoundTransaction(
        merchant_id=merchant_id,
        product_id=product_id,
        quantity=quantity,
        amount_inr=amount,
        currency=currency,
        policy_version=decision.policy_version,
        offer_version=offer_version,
        expires_at=expires_at,
        nonce=nonce,
    )


def build_bound_transaction(
    *,
    offer: ProvenancedOffer,
    decision: PolicyDecision,
    quantity: int,
    nonce: str,
    expires_at: datetime,
) -> BoundTransaction:
    """Build the canonical transaction an authorization will commit to."""
    return _build_bound_transaction_from_values(
        offer_id=offer.offer_id,
        offer_valid=offer.valid,
        merchant_id=offer.merchant_id.value,
        product_id=offer.product_id.value,
        unit_amount_inr=offer.amount_inr.value,
        currency=offer.currency.value,
        offer_version=offer.offer_version,
        decision=decision,
        quantity=quantity,
        expires_at=expires_at,
        nonce=nonce,
    )


async def build_bound_transaction_from_selected_offer(
    session: AsyncSession,
    *,
    mission_id: uuid.UUID,
    candidate: OfferCandidate,
    selected_offer_version: str,
    decision: PolicyDecision,
    quantity: int,
    nonce: str,
    expires_at: datetime,
) -> BoundTransaction:
    """Reload and reconcile the selected offer before minting authorization.

    The candidate contributes one opaque identifier. Every authority-bearing
    transaction value is reloaded from the server-held structured ``offers``
    row under a row lock, and its content fingerprint is recomputed instead of
    trusting the stored version column alone. A missing row, a changed row, or
    stale version metadata produces the same stable fail-closed reason.

    The row is server-controlled after ingress, but its product/price content
    originated with the merchant and is not cryptographically authenticated.
    C1 treats database integrity and the merchant adapter registration as TCB
    assumptions; this function does not pretend to add merchant signatures.
    """
    result = await session.execute(
        select(Offer)
        .where(
            Offer.id == candidate.offer_id,
            Offer.mission_id == mission_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise BindRefusedOfferChanged(
            mission_id=mission_id,
            offer_id=candidate.offer_id,
            detail="the selected offer is absent at bind time",
        )

    current_version = compute_offer_version(
        merchant_id=row.merchant_id,
        product_id=row.product_id,
        amount_inr=row.amount_inr,
        currency=row.currency,
        rating=row.rating,
        in_stock=row.in_stock,
        offered_at=as_utc(row.offered_at),
    )
    if row.offer_version != current_version or current_version != selected_offer_version:
        raise BindRefusedOfferChanged(
            mission_id=mission_id,
            offer_id=candidate.offer_id,
            detail="selected offer version does not match the bind-time offer record",
        )

    if not row.valid:
        # Ranking rejected this offer after the selector saw it. Reached only by
        # a genuine race against the authoritative row, so it is a bind-time
        # refusal like any other drift — not the programming error that the
        # shared builder's `require` guards against on the in-memory path.
        raise BindRefusedOfferChanged(
            mission_id=mission_id,
            offer_id=candidate.offer_id,
            detail="the selected offer was rejected before bind time",
            invariant_id=OFFER_VALID_INVARIANT,
        )

    return _build_bound_transaction_from_values(
        offer_id=row.id,
        offer_valid=row.valid,
        # Trusted transport identity persisted at ingress, never the payload's
        # claimed merchant identity retained in ``Offer.raw``.
        merchant_id=row.merchant_id,
        product_id=row.product_id,
        unit_amount_inr=row.amount_inr,
        currency=row.currency,
        offer_version=current_version,
        decision=decision,
        quantity=quantity,
        nonce=nonce,
        expires_at=expires_at,
    )


def digests_match(expected_digest: str, transaction: BoundTransaction) -> bool:
    """Constant-shape comparison of a recorded digest against a live transaction.

    Both operands are server-computed SHA-256 hex strings of public transaction
    fields, so a plain comparison is appropriate — there is no secret to leak
    through timing here. (The nonce is inside the *preimage*, never compared.)
    """
    return expected_digest == transaction.digest()
