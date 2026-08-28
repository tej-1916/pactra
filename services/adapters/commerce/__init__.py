"""Commerce adapter family: merchant / catalog / offer semantics."""

from __future__ import annotations

from services.adapters.commerce.base import FAMILY, CommerceAdapter
from services.adapters.commerce.pactra_commerce import (
    DESCRIPTOR as PACTRA_COMMERCE_DESCRIPTOR,
)
from services.adapters.commerce.pactra_commerce import PactraCommerceAdapter

__all__ = [
    "FAMILY",
    "PACTRA_COMMERCE_DESCRIPTOR",
    "CommerceAdapter",
    "PactraCommerceAdapter",
]
