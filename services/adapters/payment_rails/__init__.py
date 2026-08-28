"""The payment-rail adapter family. See ``base.py`` — it documents, not wraps."""

from __future__ import annotations

from services.adapters.payment_rails.base import (
    FAMILY,
    PAYMENT_RAIL_PROTOCOL,
    RAIL_REGISTRY_MODULE,
    RAIL_STATUS,
    describe_payment_rails,
)

__all__ = [
    "FAMILY",
    "PAYMENT_RAIL_PROTOCOL",
    "RAIL_REGISTRY_MODULE",
    "RAIL_STATUS",
    "describe_payment_rails",
]
