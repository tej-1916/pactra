"""Provenance & taint primitives (typed domain objects, not prompts).

Every security-sensitive value can be wrapped in a ``Provenanced[T]`` that
records where it came from, what authority the source held, its trust level, and
whether it is tainted (untrusted). Taint and provenance travel *with* the value
through transformations so the kernel can always answer: where did this come
from, who was allowed to produce it, and may it influence a sensitive field.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum, IntEnum
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")
U = TypeVar("U")


class AuthorityLevel(IntEnum):
    """Ordered authority lattice. Higher value = higher authority.

    ``USER_POLICY`` is deliberately NOT called "user-signed": nothing in the
    current phase cryptographically signs a user policy. It is authoritative
    because it is established server-side at the trusted API boundary, not
    because it carries a verifiable signature. A ``VERIFIED_USER_POLICY`` level
    may be introduced once Phase 3 implements real signing.
    """

    MERCHANT_DATA = 10
    AGENT_PROPOSAL = 20
    TRUSTED_INTERNAL_SERVICE = 30
    AUTHORIZATION = 40
    SYSTEM_SECURITY_POLICY = 50
    USER_POLICY = 60


class TrustLevel(str, Enum):
    AUTHORITATIVE = "authoritative"
    TRUSTED = "trusted"
    UNTRUSTED = "untrusted"


class ProvenanceMeta(BaseModel):
    """Serializable provenance record (no value payload)."""

    model_config = ConfigDict(extra="forbid")

    source: str
    authority: AuthorityLevel
    trust: TrustLevel
    tainted: bool
    transformed: bool = False


class Provenanced(BaseModel, Generic[T]):
    """A value carrying its provenance and taint."""

    model_config = ConfigDict(extra="forbid")

    value: T
    source: str
    authority: AuthorityLevel
    trust: TrustLevel
    tainted: bool
    transformed: bool = False

    def meta(self) -> ProvenanceMeta:
        return ProvenanceMeta(
            source=self.source,
            authority=self.authority,
            trust=self.trust,
            tainted=self.tainted,
            transformed=self.transformed,
        )

    def map(self, fn: Callable[[T], U]) -> Provenanced[U]:
        """Transform the value, preserving provenance and marking it transformed.

        Taint is *sticky*: a transformed untrusted value stays untrusted.
        """
        return Provenanced[U](
            value=fn(self.value),
            source=self.source,
            authority=self.authority,
            trust=self.trust,
            tainted=self.tainted,
            transformed=True,
        )


def is_tainted(p: Provenanced[Any]) -> bool:
    return p.tainted


# --------------------------------------------------------------------------- #
# Constructors
# --------------------------------------------------------------------------- #
def authoritative(value: T, source: str = "user-policy") -> Provenanced[T]:
    return Provenanced[T](
        value=value,
        source=source,
        authority=AuthorityLevel.USER_POLICY,
        trust=TrustLevel.AUTHORITATIVE,
        tainted=False,
    )


def system_value(value: T, source: str = "system-policy") -> Provenanced[T]:
    return Provenanced[T](
        value=value,
        source=source,
        authority=AuthorityLevel.SYSTEM_SECURITY_POLICY,
        trust=TrustLevel.TRUSTED,
        tainted=False,
    )


def trusted_value(value: T, source: str) -> Provenanced[T]:
    """A value produced by a trusted internal service (e.g. the merchant
    transport establishing an authenticated identity, or the server-owned
    merchant registry). Not authoritative over user policy, but not merchant
    data either — it is untainted because no untrusted party can influence it."""
    return Provenanced[T](
        value=value,
        source=source,
        authority=AuthorityLevel.TRUSTED_INTERNAL_SERVICE,
        trust=TrustLevel.TRUSTED,
        tainted=False,
    )


def agent_value(value: T, source: str = "buyer-agent") -> Provenanced[T]:
    return Provenanced[T](
        value=value,
        source=source,
        authority=AuthorityLevel.AGENT_PROPOSAL,
        trust=TrustLevel.UNTRUSTED,
        tainted=True,
    )


def untrusted(value: T, source: str) -> Provenanced[T]:
    """Merchant-controlled (lowest authority, always tainted)."""
    return Provenanced[T](
        value=value,
        source=source,
        authority=AuthorityLevel.MERCHANT_DATA,
        trust=TrustLevel.UNTRUSTED,
        tainted=True,
    )
