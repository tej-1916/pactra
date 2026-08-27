"""Kernel offer representation: value/provenance coupling that cannot be bypassed.

Unlike the ``NormalizedOffer`` DTO (which stores plain values plus a detachable
provenance sidecar for persistence/API), every security-sensitive field of a
``ProvenancedOffer`` *is* a ``Provenanced[T]``. There is no way to read a value
without its provenance travelling with it, so the kernel can never accidentally
act on a merchant value as if it were trusted.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from packages.schemas.domain import NormalizedOffer, ReasonCode, new_uuid
from packages.schemas.provenance import Provenanced

# The full set of merchant-controlled fields that must retain provenance/taint.
SENSITIVE_FIELDS = (
    "merchant_id",
    "merchant_name",
    "merchant_trust",
    "product_id",
    "title",
    "amount_inr",
    "currency",
    "rating",
    "in_stock",
    "offered_at",
)


class ProvenancedOffer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offer_id: uuid.UUID = Field(default_factory=new_uuid)
    merchant_id: Provenanced[str]
    merchant_name: Provenanced[str]
    merchant_trust: Provenanced[float]
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
        if not isinstance(value, Provenanced):
            raise TypeError(f"{name} is not a provenance-coupled field")
        return value

    def meta_map(self) -> dict:
        return {name: self.field(name).meta() for name in SENSITIVE_FIELDS}

    def to_normalized(self) -> NormalizedOffer:
        """Project to the persistence/API DTO, preserving provenance metadata."""
        return NormalizedOffer(
            offer_id=self.offer_id,
            merchant_id=self.merchant_id.value,
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
