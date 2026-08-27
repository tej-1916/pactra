"""Merchant agent interface. Merchant responses are UNTRUSTED."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from packages.schemas.domain import MissionConstraints, RawMerchantOffer


@runtime_checkable
class MerchantAgent(Protocol):
    merchant_id: str
    merchant_name: str

    def quote(self, constraints: MissionConstraints, quantity: int) -> list[RawMerchantOffer]:
        """Return raw offers for the requested category. Deterministic."""
        ...
