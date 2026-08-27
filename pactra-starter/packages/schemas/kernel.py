"""Kernel offer representation: value/provenance coupling that cannot be bypassed.

Unlike the ``NormalizedOffer`` DTO (which stores plain values plus a detachable
provenance sidecar for persistence/API), every security-sensitive field of a
``ProvenancedOffer`` *is* a ``Provenanced[T]``. There is no way to read a value
without its provenance travelling with it, so the kernel can never accidentally
act on a merchant value as if it were trusted.

Fields fall into two groups with different origins:

* ``IDENTITY_FIELDS`` are produced by trusted server-side components — the
  merchant transport (authenticated identity) and the server-owned merchant
  registry (display name, trust score). They are untainted because no untrusted
  party can influence them.
* ``MERCHANT_FIELDS`` come from the merchant payload and are always untrusted
  and tainted, including ``claimed_merchant_id`` — the identity the payload
  *asserted*, kept only so a spoof attempt stays visible and auditable.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from packages.schemas.domain import NormalizedOffer, ReasonCode, new_uuid
from packages.schemas.invariants import require
from packages.schemas.provenance import Provenanced

# Trusted, server-owned. Never derived from a merchant payload.
IDENTITY_FIELDS = (
    "merchant_id",
    "merchant_name",
    "merchant_trust",
)

# Merchant-controlled fields that must retain provenance/taint.
MERCHANT_FIELDS = (
    "claimed_merchant_id",
    "product_id",
    "title",
    "amount_inr",
    "currency",
    "rating",
    "in_stock",
    "offered_at",
)

# Every provenance-coupled field on the offer.
SENSITIVE_FIELDS = IDENTITY_FIELDS + MERCHANT_FIELDS


class ProvenancedOffer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offer_id: uuid.UUID = Field(default_factory=new_uuid)
    # --- trusted (transport identity + server-owned registry) ---
    merchant_id: Provenanced[str]
    merchant_name: Provenanced[str]
    merchant_trust: Provenanced[float]
    # --- untrusted (merchant payload) ---
    claimed_merchant_id: Provenanced[str]
    product_id: Provenanced[str]
    title: Provenanced[str]
    amount_inr: Provenanced[int]
    currency: Provenanced[str]
    rating: Provenanced[float]
    in_stock: Provenanced[bool]
    offered_at: Provenanced[datetime]
    valid: bool = True
    rejection_reasons: list[ReasonCode] = Field(default_factory=list)
    rank: int | None = None

    def field(self, name: str) -> Provenanced:
        value = getattr(self, name)
        require(
            isinstance(value, Provenanced),
            "offer.field_is_provenance_coupled",
            f"'{name}' is not a provenance-coupled field",
        )
        return value

    @property
    def identity_mismatch(self) -> bool:
        """True when the payload claimed an identity other than the merchant the
        transport actually authenticated — i.e. an identity spoof attempt."""
        return self.claimed_merchant_id.value != self.merchant_id.value

    def meta_map(self) -> dict:
        return {name: self.field(name).meta() for name in SENSITIVE_FIELDS}

    def to_normalized(self) -> NormalizedOffer:
        """Project to the persistence/API DTO, preserving provenance metadata."""
        return NormalizedOffer(
            offer_id=self.offer_id,
            merchant_id=self.merchant_id.value,
            claimed_merchant_id=self.claimed_merchant_id.value,
            merchant_name=self.merchant_name.value,
            merchant_trust=self.merchant_trust.value,
            product_id=self.product_id.value,
            title=self.title.value,
            amount_inr=self.amount_inr.value,
            currency=self.currency.value,
            rating=self.rating.value,
            in_stock=self.in_stock.value,
            offered_at=self.offered_at.value,
            valid=self.valid,
            rejection_reasons=self.rejection_reasons,
            rank=self.rank,
            provenance=self.meta_map(),
        )
