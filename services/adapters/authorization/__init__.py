"""Payment-authorization adapter family: candidate requests, never artifacts."""

from __future__ import annotations

from services.adapters.authorization.base import FAMILY, PaymentAuthorizationAdapter
from services.adapters.authorization.pactra_intent import (
    DESCRIPTOR as PACTRA_INTENT_DESCRIPTOR,
)
from services.adapters.authorization.pactra_intent import PactraAuthorizationIntentAdapter

__all__ = [
    "FAMILY",
    "PACTRA_INTENT_DESCRIPTOR",
    "PactraAuthorizationIntentAdapter",
    "PaymentAuthorizationAdapter",
]
