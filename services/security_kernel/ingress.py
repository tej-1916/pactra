"""Trusted ingress boundary.

This is the ONLY place merchant data is turned into kernel values. Authority and
trust are assigned here based on the *authenticated source*, never read from the
wire. A merchant payload that tries to declare its own authority, trust, or
`tainted=False` cannot succeed: `RawMerchantOffer` ignores unknown fields, and
this adapter hard-codes MERCHANT_DATA / UNTRUSTED / tainted for every payload
value.

Identity and trust do not come from the payload at all. They arrive in a
``MerchantContext`` supplied by the merchant transport (authenticated identity)
and the server-owned ``MerchantRegistry`` (display name, trust score). The
payload's ``merchant_id`` survives only as `claimed_merchant_id`, which the
kernel compares against the authenticated identity so a spoof attempt is
detected rather than believed.

Likewise, user policy values are wrapped as authoritative only here, server-side,
so untrusted input can never manufacture USER_POLICY authority.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, TypeVar

from packages.schemas.domain import MissionConstraints, RawMerchantOffer
from packages.schemas.invariants import require
from packages.schemas.kernel import ProvenancedOffer
from packages.schemas.merchant import MerchantContext
from packages.schemas.provenance import (
    Provenanced,
    authoritative,
    system_value,
    trusted_value,
    untrusted,
)

T = TypeVar("T")

# Every user-policy field the kernel holds at USER_POLICY authority. Extending
# this set is how a policy field becomes unforgeable by lower-authority sources.
PROTECTED_POLICY_FIELDS = (
    "soft_budget_inr",
    "hard_limit_inr",
    "currency",
    "min_rating",
    "allowed_merchants",
    "blocked_merchants",
    "min_merchant_trust",
)


def _normalized_instant(value: datetime) -> datetime:
    """Collapse an offset-aware merchant timestamp to the UTC instant it names.

    The same instant may arrive as `17:30+05:30` or `12:00Z`. Both must produce
    one offer fingerprint and one stored value, because the bind-time recompute
    reads the row back through `as_utc` and would otherwise refuse a perfectly
    unchanged offer. Normalizing here, at the trust boundary, keeps the
    selection-time and bind-time views of `offered_at` identical.

    A NAIVE datetime is deliberately left alone: it names no instant, and
    attaching UTC to it here would silently invent one. It stays naive so the
    canonical encoder still fails it closed at fingerprint time.
    """
    if value.tzinfo is None or value.utcoffset() is None:
        return value
    return value.astimezone(timezone.utc)


def ingest_merchant_offer(raw: RawMerchantOffer, context: MerchantContext) -> ProvenancedOffer:
    """Assign provenance/taint to every merchant-controlled value.

    `context` is the trusted merchant context established by the transport; it
    is passed separately from `raw` precisely so that nothing in the payload can
    influence identity, trust, or the provenance source string.
    """
    identity = context.identity
    require(
        identity.merchant_id == context.record.merchant_id,
        "merchant.context_identity_matches_record",
        f"identity '{identity.merchant_id}' != record '{context.record.merchant_id}'",
    )

    # PROVENANCE SOURCE IS THE AUTHENTICATED IDENTITY — never raw.merchant_id.
    source = f"merchant:{identity.merchant_id}"
    identity_source = f"merchant-identity:{identity.merchant_id}"
    registry_source = f"merchant-registry:{identity.merchant_id}"

    return ProvenancedOffer(
        # Trusted: established by the transport / server-owned registry.
        merchant_id=trusted_value(identity.merchant_id, identity_source),
        merchant_name=trusted_value(context.record.display_name, registry_source),
        merchant_trust=system_value(context.record.trust_score, source=registry_source),
        # Untrusted: merchant payload. The claimed identity is kept ONLY as a
        # claim to be verified — it is tainted like any other merchant value.
        claimed_merchant_id=untrusted(raw.merchant_id, source),
        product_id=untrusted(raw.product_id, source),
        title=untrusted(raw.title, source),
        # amount is a transform of the raw price; taint is sticky through it.
        amount_inr=untrusted(raw.price, source).map(lambda p: int(round(p))),
        currency=untrusted(raw.currency.upper(), source),
        rating=untrusted(raw.rating, source),
        in_stock=untrusted(raw.in_stock, source),
        offered_at=untrusted(_normalized_instant(raw.offered_at), source),
    )


def ingest_user_policy_value(field: str, value: T) -> Provenanced[T]:
    """Wrap a user-policy scalar as authoritative. Only trusted server-side code
    (the API boundary / config) may call this."""
    return authoritative(value, source=f"user-policy:{field}")


def protected_policy_values(constraints: MissionConstraints) -> dict[str, Provenanced[Any]]:
    """The user-policy fields the kernel protects at USER_POLICY authority.

    This covers the budget ceilings *and* the security-sensitive selection
    policy: currency, minimum rating, the merchant allow/block lists, and the
    minimum merchant trust. A merchant that claims any of these is attempting to
    widen the ground it is judged on, which the authority lattice must refuse.
    """
    return {
        field: ingest_user_policy_value(field, getattr(constraints, field))
        for field in PROTECTED_POLICY_FIELDS
    }
