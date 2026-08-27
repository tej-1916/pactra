"""Trusted merchant identity types.

The central rule of this module: **a merchant never tells us who it is.**

``MerchantIdentity`` is produced by the merchant transport/adapter from the
connection it authenticated. ``MerchantRecord`` (reputation / trust score) is
owned by the server-side ``MerchantRegistry``. ``MerchantContext`` couples the
two and is the only thing downstream code may use to decide *which* merchant
produced an offer and *how much* that merchant is trusted.

Nothing here is ever constructed from a ``RawMerchantOffer`` payload. The
payload's ``merchant_id`` is retained separately as a *claim* and verified
against the authenticated identity at ingress.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from packages.schemas.domain import RawMerchantOffer


class MerchantAuthMethod(str, Enum):
    """How the transport established the merchant's identity.

    Phase 2 only has ``IN_PROCESS_ADAPTER``: the merchant agent is registered
    server-side and reached in-process, so its identity comes from the trusted
    registration rather than from anything it sends. This is explicitly NOT a
    cryptographic authentication claim — mutual TLS / signed assertions arrive
    with Phase 3.
    """

    IN_PROCESS_ADAPTER = "in_process_adapter"


class MerchantIdentity(BaseModel):
    """The authenticated identity of the merchant on the other end of a
    connection. Established by the transport, immutable thereafter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    merchant_id: str = Field(min_length=1, max_length=120)
    auth_method: MerchantAuthMethod
    channel: str = Field(min_length=1, max_length=120)


class MerchantRecord(BaseModel):
    """Server-owned reputation record. The `trust_score` here is the ONLY
    merchant trust value any decision component may read."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    merchant_id: str = Field(min_length=1, max_length=120)
    display_name: str = Field(min_length=1, max_length=200)
    trust_score: float = Field(ge=0.0, le=1.0)
    known: bool = True
    active: bool = True


class MerchantContext(BaseModel):
    """Trusted context for one merchant: who they are + what we think of them.

    Passed alongside (never inside) the untrusted payload.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    identity: MerchantIdentity
    record: MerchantRecord

    @property
    def merchant_id(self) -> str:
        return self.identity.merchant_id

    @property
    def display_name(self) -> str:
        return self.record.display_name

    @property
    def trust_score(self) -> float:
        return self.record.trust_score


class AuthenticatedQuote(BaseModel):
    """One merchant's response, bound to the identity that actually produced it.

    The orchestrator carries these instead of a flat list of offers, so the
    authenticated identity is never lost between transport and ingress.
    """

    model_config = ConfigDict(extra="forbid")

    context: MerchantContext
    offers: list[RawMerchantOffer] = Field(default_factory=list)
