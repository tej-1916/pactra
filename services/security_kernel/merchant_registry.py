"""Server-owned merchant reputation registry.

Merchant trust is a security control, so it is owned by the platform and never
by the merchant. A merchant payload has no field capable of carrying a trust
score (see ``RawMerchantOffer``); the only source of ``merchant_trust`` anywhere
in the system is a ``MerchantRecord`` returned from here.

Authentication vs. reputation are deliberately separate concerns. The transport
may establish an authenticated identity for a merchant this registry has never
heard of; such a merchant is simply *unknown* and receives ``UNKNOWN_TRUST``
(0.0), which fails any positive ``min_merchant_trust`` constraint. Deciding
whether an authenticated merchant is allowed to trade is the policy engine's
job, not the registry's.
"""

from __future__ import annotations

from packages.schemas.merchant import MerchantContext, MerchantIdentity, MerchantRecord

# An authenticated but unrecognized merchant earns no trust by default.
UNKNOWN_TRUST = 0.0

# Trusted, in-code reputation table. In later phases this may move to persistent
# application storage, but it is always server-owned and never merchant-writable.
_RECORDS: dict[str, MerchantRecord] = {
    "merchant_a": MerchantRecord(
        merchant_id="merchant_a",
        display_name="Aurora Audio",
        trust_score=0.9,
    ),
    "merchant_b": MerchantRecord(
        merchant_id="merchant_b",
        display_name="Nimbus Devices",
        trust_score=0.75,
    ),
}


class MerchantRegistry:
    def __init__(self, records: dict[str, MerchantRecord] | None = None) -> None:
        self._records = dict(_RECORDS if records is None else records)

    def is_known(self, merchant_id: str) -> bool:
        return merchant_id in self._records

    def record_for(self, merchant_id: str) -> MerchantRecord:
        """Return the server-owned record for a merchant. Unknown merchants get
        a synthesized zero-trust record rather than an error, so an
        unrecognized-but-authenticated merchant is still adjudicated by policy
        instead of silently vanishing."""
        record = self._records.get(merchant_id)
        if record is not None:
            return record
        return MerchantRecord(
            merchant_id=merchant_id,
            display_name=merchant_id,
            trust_score=UNKNOWN_TRUST,
            known=False,
        )

    def trust_for(self, merchant_id: str) -> float:
        return self.record_for(merchant_id).trust_score

    def context_for(self, identity: MerchantIdentity) -> MerchantContext:
        """Bind an authenticated identity to its server-owned reputation."""
        return MerchantContext(
            identity=identity,
            record=self.record_for(identity.merchant_id),
        )


def default_merchant_registry() -> MerchantRegistry:
    return MerchantRegistry()
