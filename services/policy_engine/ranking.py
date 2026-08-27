"""Deterministic offer ranking over the coupled kernel representation.

Only valid offers are ranked. Values are read from their provenance-coupled
fields (`.value`), so ranking never operates on a detached, unlabelled value.
Ranking is a total order for stable results:
  1. higher rating (quality proxy) first
  2. lower price
  3. higher merchant trust
  4. merchant_id, then product_id (final deterministic tie-break)
"""

from __future__ import annotations

from packages.schemas.kernel import ProvenancedOffer


def _sort_key(o: ProvenancedOffer) -> tuple:
    return (
        -o.rating.value,
        o.amount_inr.value,
        -o.merchant_trust.value,
        o.merchant_id.value,
        o.product_id.value,
    )


def rank_offers(offers: list[ProvenancedOffer]) -> list[ProvenancedOffer]:
    valid = [o for o in offers if o.valid]
    ranked = sorted(valid, key=_sort_key)
    for i, offer in enumerate(ranked, start=1):
        offer.rank = i
    return ranked


def best_offer(offers: list[ProvenancedOffer]) -> ProvenancedOffer | None:
    ranked = rank_offers(offers)
    return ranked[0] if ranked else None
