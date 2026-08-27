"""Offer normalization.

Merchant offers are first passed through the trusted ingress together with the
``MerchantContext`` the transport authenticated, producing a
``ProvenancedOffer`` — the coupled kernel representation. Normalization then
applies structural/constraint checks to mark each offer valid or invalid,
reading values via `.value`.

Two properties matter here:

* Identity spoofing is caught first. If the payload claimed a merchant_id other
  than the authenticated one, the offer is rejected outright with
  MERCHANT_IDENTITY_MISMATCH — a spoofed offer never gets the chance to satisfy
  an allow-list.
* Allow/block/trust checks read the AUTHENTICATED identity and the SERVER-OWNED
  trust score, so a merchant cannot talk its way past them.

A normalized offer is STRUCTURALLY VALIDATED BUT STILL UNTRUSTED: passing these
checks never launders merchant taint. The free-form `description` is dropped at
ingress and never reaches this layer.
"""

from __future__ import annotations

from packages.schemas.domain import MissionConstraints, RawMerchantOffer, ReasonCode
from packages.schemas.kernel import ProvenancedOffer
from packages.schemas.merchant import AuthenticatedQuote, MerchantContext

from services.security_kernel.ingress import ingest_merchant_offer


def normalize_offer(
    raw: RawMerchantOffer,
    context: MerchantContext,
    constraints: MissionConstraints,
) -> ProvenancedOffer:
    offer = ingest_merchant_offer(raw, context)
    reasons: list[ReasonCode] = []

    # Identity spoof: the payload claimed to be someone else.
    if offer.identity_mismatch:
        reasons.append(ReasonCode.MERCHANT_IDENTITY_MISMATCH)

    if offer.currency.value != constraints.currency:
        reasons.append(ReasonCode.CURRENCY_NOT_ALLOWED)
    if not offer.in_stock.value:
        reasons.append(ReasonCode.OUT_OF_STOCK)
    if offer.rating.value < constraints.min_rating:
        reasons.append(ReasonCode.RATING_BELOW_MIN)
    # Server-owned trust score — never a merchant-supplied one.
    if offer.merchant_trust.value < constraints.min_merchant_trust:
        reasons.append(ReasonCode.MERCHANT_TRUST_TOO_LOW)
    # Allow/block evaluated against the AUTHENTICATED identity.
    if constraints.allowed_merchants is not None and (
        offer.merchant_id.value not in constraints.allowed_merchants
    ):
        reasons.append(ReasonCode.MERCHANT_NOT_ALLOWED)
    if offer.merchant_id.value in constraints.blocked_merchants:
        reasons.append(ReasonCode.BLOCKED_MERCHANT)

    offer.valid = len(reasons) == 0
    offer.rejection_reasons = reasons
    return offer


def normalize_offers(
    quotes: list[AuthenticatedQuote], constraints: MissionConstraints
) -> list[ProvenancedOffer]:
    """Normalize every authenticated merchant's offers, keeping each offer bound
    to the identity that produced it."""
    return [
        normalize_offer(raw, quote.context, constraints) for quote in quotes for raw in quote.offers
    ]
