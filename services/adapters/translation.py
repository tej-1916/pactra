"""What a concrete adapter hands back, and the provenance helper it builds with.

Split out from ``translate.py`` so the family base classes can name the return
type without importing the registry — the registry has to import the base
classes to check that an implementation belongs to its declared family, and a
cycle between the two would be resolved by somebody moving a check.

WHY AN ADAPTER RETURNS A RESULT INSTEAD OF AN ENVELOPE
    An ``AdapterEnvelope`` carries server-owned identity: adapter id, protocol
    name, adapter version. If an adapter built its own envelope it would be
    stating its own identity, and a compromised or simply careless adapter could
    state a different one. So adapters return the part they actually know —
    the canonical payload, its provenance, and any warnings — and
    ``services.adapters.translate`` stamps the identity from the registry's
    descriptor. Caller-provided adapter metadata is never trusted adapter
    identity, and neither is adapter-provided adapter metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar

from packages.schemas.provenance import AuthorityLevel, ProvenanceMeta, TrustLevel

from services.adapters.models import AdapterWarning

P = TypeVar("P")


@dataclass(frozen=True)
class TranslationResult(Generic[P]):
    """One adapter's output, before server-owned identity is attached."""

    canonical_payload: P
    provenance: dict[str, ProvenanceMeta] = field(default_factory=dict)
    warnings: tuple[AdapterWarning, ...] = ()


def external_provenance(source: str) -> ProvenanceMeta:
    """Provenance for a value that came off a protocol wire.

    Every field of this is fixed rather than parameterized, and that is the
    point: an adapter has no argument through which it could produce a value at
    higher authority, lower taint, or greater trust. It reuses the kernel's own
    ``AuthorityLevel`` / ``TrustLevel`` rather than a parallel adapter
    vocabulary, so downstream code compares one scale, not two.

    ``AGENT_PROPOSAL`` rather than ``MERCHANT_DATA``: the sender is an external
    agent or system making a proposal, and the merchant-specific level is
    assigned later by ``ingest_merchant_offer`` when a transport-authenticated
    merchant identity actually exists. Overstating it as merchant data here
    would attribute the value to a merchant nobody has authenticated.

    ``transformed=True``: translation IS a transformation, and taint is sticky
    through it exactly as it is through ``Provenanced.map``.
    """
    return ProvenanceMeta(
        source=source,
        authority=AuthorityLevel.AGENT_PROPOSAL,
        trust=TrustLevel.UNTRUSTED,
        tainted=True,
        transformed=True,
    )


def provenance_source(adapter_id: str, claimed_id: str) -> str:
    """The provenance ``source`` string for a translated value.

    Names the registered adapter AND the identity the caller claimed, in that
    order. The adapter id is server-owned and therefore reliable; the claimed id
    is a claim and is marked as such by the ``claim:`` prefix, so nothing
    reading the string can mistake it for an authenticated identity.
    """
    return f"adapter:{adapter_id}:claim:{claimed_id}"
