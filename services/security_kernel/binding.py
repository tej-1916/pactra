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

from datetime import datetime

from packages.schemas.domain import PolicyDecision, PolicyOutcome
from packages.schemas.invariants import InvariantViolation, require
from packages.schemas.kernel import ProvenancedOffer
from packages.schemas.transaction import BoundTransaction

# Policy outcomes that may produce an authorization at all. A DENY decision
# never yields a bound transaction: NO VALID AUTHORIZATION -> NO PAYMENT.
AUTHORIZABLE_OUTCOMES = frozenset({PolicyOutcome.ALLOW, PolicyOutcome.REQUIRE_APPROVAL})


def build_bound_transaction(
    *,
    offer: ProvenancedOffer,
    decision: PolicyDecision,
    quantity: int,
    nonce: str,
    expires_at: datetime,
) -> BoundTransaction:
    """Build the canonical transaction an authorization will commit to."""
    require(
        decision.decision in AUTHORIZABLE_OUTCOMES,
        "binding.decision_is_authorizable",
        f"cannot bind a transaction for a {decision.decision.value} decision",
    )
    require(
        offer.valid,
        "binding.offer_is_valid",
        f"offer {offer.offer_id} was rejected and cannot be bound",
    )
    require(
        decision.selected_offer_id == offer.offer_id,
        "binding.offer_matches_decision",
        f"decision selected {decision.selected_offer_id}, not offer {offer.offer_id}",
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
        amount == offer.amount_inr.value * quantity,
        "binding.amount_matches_offer_and_quantity",
        f"decision amount {amount} != unit {offer.amount_inr.value} x qty {quantity}",
    )

    return BoundTransaction(
        # AUTHENTICATED identity — never offer.claimed_merchant_id.
        merchant_id=offer.merchant_id.value,
        product_id=offer.product_id.value,
        quantity=quantity,
        amount_inr=amount,
        currency=offer.currency.value,
        policy_version=decision.policy_version,
        offer_version=offer.offer_version,
        expires_at=expires_at,
        nonce=nonce,
    )


def digests_match(expected_digest: str, transaction: BoundTransaction) -> bool:
    """Constant-shape comparison of a recorded digest against a live transaction.

    Both operands are server-computed SHA-256 hex strings of public transaction
    fields, so a plain comparison is appropriate — there is no secret to leak
    through timing here. (The nonce is inside the *preimage*, never compared.)
    """
    return expected_digest == transaction.digest()
