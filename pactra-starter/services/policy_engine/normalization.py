"""Offer normalization.

Merchant offers are first passed through the trusted ingress (which assigns
provenance/taint), producing a ``ProvenancedOffer`` — the coupled kernel
representation. Normalization then applies structural/constraint checks to mark
each offer valid or invalid, reading values via `.value`.

A normalized offer is STRUCTURALLY VALIDATED BUT STILL UNTRUSTED: passing these
checks never launders merchant taint. The free-form `description` is dropped at
ingress and never reaches this layer.
"""

from __future__ import annotations

from packages.schemas.domain import MissionConstraints, RawMerchantOffer, ReasonCode
from packages.schemas.kernel import ProvenancedOffer

from services.security_kernel.ingress import ingest_merchant_offer


def normalize_offer(raw: RawMerchantOffer, constraints: MissionConstraints) -> ProvenancedOffer:
    offer = ingest_merchant_offer(raw)
    reasons: list[ReasonCode] = []

    if offer.currency.value != constraints.currency:
        reasons.append(ReasonCode.CURRENCY_NOT_ALLOWED)
    if not offer.in_stock.value:
        reasons.append(ReasonCode.OUT_OF_STOCK)
    if offer.rating.value < constraints.min_rating:
        reasons.append(ReasonCode.RATING_BELOW_MIN)
    if offer.merchant_trust.value < constraints.min_merchant_trust:
        reasons.append(ReasonCode.MERCHANT_TRUST_TOO_LOW)
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
    raws: list[RawMerchantOffer], constraints: MissionConstraints
) -> list[ProvenancedOffer]:
    return [normalize_offer(r, constraints) for r in raws]
