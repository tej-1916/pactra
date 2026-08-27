"""Canonical transaction representation and transaction binding.

A ``BoundTransaction`` is the exact, complete description of what a user
approved. Its digest is the commitment: an authorization carries the digest,
and at consumption time the digest of the *current* transaction is recomputed
and compared. If the merchant changed the price, the product, the merchant, the
quantity, the currency, or either version stamp, the digests differ and the
authorization is unusable.

The digest is produced by ``packages.schemas.canonical`` — a type-tagged,
domain-separated, sorted-key encoding — never by concatenating strings. See
that module for why concatenation is unsafe.

``BOUND_FIELDS`` is the authoritative list of what the digest covers. It is
compared against the model's own field set by a test, so adding a field to
``BoundTransaction`` without adding it to the digest fails the suite rather
than silently shrinking the binding.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from packages.schemas.canonical import CanonicalValue, canonical_digest
from packages.schemas.invariants import require

# Domain separator for the transaction-binding digest. Bump the suffix if the
# encoding ever changes, so old and new digests can never be confused.
BINDING_VERSION = "pactra-txn-bind-v1"

# Domain separator for the offer content fingerprint.
OFFER_VERSION_DOMAIN = "pactra-offer-version-v1"

# Every field covered by the transaction digest. Mutating ANY of these after
# approval invalidates the authorization.
BOUND_FIELDS: tuple[str, ...] = (
    "merchant_id",
    "product_id",
    "quantity",
    "amount_inr",
    "currency",
    "policy_version",
    "offer_version",
    "expires_at",
    "nonce",
)

# A nonce is 32 bytes of CSPRNG entropy rendered as hex (64 characters).
NONCE_HEX_LENGTH = 64


class BoundTransaction(BaseModel):
    """The exact transaction an authorization is bound to.

    Frozen: once built, a bound transaction cannot be edited in place. A
    "changed" transaction is necessarily a *different* object with a different
    digest, which is the whole point of the binding.

    ``merchant_id`` here is always the transport-AUTHENTICATED merchant id, never
    a merchant's self-asserted ``claimed_merchant_id`` (see
    ``services.security_kernel.binding``).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    merchant_id: str = Field(min_length=1, max_length=120)
    product_id: str = Field(min_length=1, max_length=120)
    quantity: int = Field(ge=1, le=100)
    # A bound transaction must move a positive amount: binding a zero-amount
    # transaction would create an authorization that authorizes nothing.
    amount_inr: int = Field(ge=1)
    currency: str = Field(min_length=3, max_length=3)
    policy_version: str = Field(min_length=1, max_length=40)
    offer_version: str = Field(min_length=1, max_length=64)
    expires_at: datetime
    nonce: str = Field(
        min_length=NONCE_HEX_LENGTH,
        max_length=128,
        pattern=r"^[0-9a-f]+$",
    )

    @field_validator("currency")
    @classmethod
    def _upper_currency(cls, v: str) -> str:
        return v.upper()

    @model_validator(mode="after")
    def _expiry_is_timezone_aware(self) -> BoundTransaction:
        require(
            self.expires_at.tzinfo is not None and self.expires_at.utcoffset() is not None,
            "transaction.expiry_is_timezone_aware",
            "expires_at must be timezone-aware; a naive expiry has no single instant",
        )
        return self

    def canonical_fields(self) -> dict[str, CanonicalValue]:
        """The exact mapping the digest is computed over."""
        return {name: getattr(self, name) for name in BOUND_FIELDS}

    def digest(self) -> str:
        """SHA-256 commitment to every bound field."""
        return canonical_digest(BINDING_VERSION, self.canonical_fields())


def compute_offer_version(
    *,
    merchant_id: str,
    product_id: str,
    amount_inr: int,
    currency: str,
    rating: float,
    in_stock: bool,
    offered_at: datetime,
) -> str:
    """Deterministic content fingerprint of a merchant offer.

    This is a SERVER-COMPUTED fingerprint of UNTRUSTED merchant content, not a
    merchant assertion: merchants have no field with which to declare a version.
    Two offers with identical security-relevant content share a version; any
    change to the content produces a different one.

    ``rating`` is scaled to hundredths because the canonical encoder rejects
    floats — binary floats have no reproducible canonical form.
    """
    return canonical_digest(
        OFFER_VERSION_DOMAIN,
        {
            "merchant_id": merchant_id,
            "product_id": product_id,
            "amount_inr": amount_inr,
            "currency": currency,
            "rating_centis": int(round(rating * 100)),
            "in_stock": in_stock,
            "offered_at": offered_at,
        },
    )[:32]
