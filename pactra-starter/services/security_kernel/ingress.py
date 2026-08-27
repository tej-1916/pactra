"""Trusted ingress boundary.

This is the ONLY place merchant data is turned into kernel values. Authority and
trust are assigned here based on the (authenticated) source — they are never read
from the wire. A merchant payload that tries to declare its own authority, trust,
or `tainted=False` cannot succeed: `RawMerchantOffer` ignores unknown fields, and
this adapter hard-codes MERCHANT_DATA / UNTRUSTED / tainted for every value.

Likewise, user policy values are wrapped as authoritative only here, server-side,
so untrusted input can never manufacture USER_SIGNED_POLICY authority.
"""

from __future__ import annotations

from packages.schemas.domain import MissionConstraints, RawMerchantOffer
from packages.schemas.kernel import ProvenancedOffer
from packages.schemas.provenance import Provenanced, authoritative, untrusted


def ingest_merchant_offer(raw: RawMerchantOffer) -> ProvenancedOffer:
    """Assign provenance/taint to every merchant-controlled value. The security
    labels are fixed here regardless of anything the payload claimed."""
    source = f"merchant:{raw.merchant_id}"
    return ProvenancedOffer(
        merchant_id=untrusted(raw.merchant_id, source),
        merchant_name=untrusted(raw.merchant_name, source),
        merchant_trust=untrusted(raw.merchant_trust, source),
        product_id=untrusted(raw.product_id, source),
        title=untrusted(raw.title, source),
        # amount is a transform of the raw price; taint is sticky through it.
        amount_inr=untrusted(raw.price, source).map(lambda p: int(round(p))),
        currency=untrusted(raw.currency.upper(), source),
        rating=untrusted(raw.rating, source),
        in_stock=untrusted(raw.in_stock, source),
        offered_at=untrusted(raw.offered_at, source),
    )


def ingest_user_policy_value(field: str, value: int) -> Provenanced[int]:
    """Wrap a user-policy scalar as authoritative. Only trusted server-side code
    (the API boundary / config) may call this."""
    return authoritative(value, source=f"user-policy:{field}")


def protected_policy_values(constraints: MissionConstraints) -> dict[str, Provenanced]:
    """The user-policy fields the kernel protects at USER_SIGNED_POLICY authority."""
    return {
        "soft_budget_inr": ingest_user_policy_value("soft_budget_inr", constraints.soft_budget_inr),
        "hard_limit_inr": ingest_user_policy_value("hard_limit_inr", constraints.hard_limit_inr),
    }
