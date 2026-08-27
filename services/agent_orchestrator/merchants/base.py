"""Merchant agent interface. Merchant RESPONSES are UNTRUSTED.

Note the asymmetry that makes the identity story work:

* ``merchant_id`` on this Protocol is the **transport-level registration id** —
  server-side configuration describing which merchant this connection belongs
  to. It is set when the merchant is wired into the orchestrator, not by
  anything the merchant sends at request time. The transport reads it to build
  a ``MerchantIdentity``.
* ``quote()`` returns ``RawMerchantOffer`` payloads, whose ``merchant_id`` is a
  *claim* the merchant makes about itself. A hostile adapter can put any value
  there; the kernel compares it against the authenticated identity above.

The two are never conflated. If they disagree, the offer is rejected with
MERCHANT_IDENTITY_MISMATCH.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from packages.schemas.domain import MissionConstraints, RawMerchantOffer


@runtime_checkable
class MerchantAgent(Protocol):
    #: Transport-level registration id (server-owned), NOT a payload value.
    merchant_id: str

    def quote(self, constraints: MissionConstraints, quantity: int) -> list[RawMerchantOffer]:
        """Return raw offers for the requested category. Deterministic."""
        ...
