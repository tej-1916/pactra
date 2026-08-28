"""Adapter families, descriptors, envelopes, and canonical candidate payloads.

THE ONE RULE THIS MODULE ENCODES
--------------------------------
An adapter translates. It never becomes an authority. Every type here is shaped
so that the second half is structural rather than a convention somebody has to
remember:

* ``SourceIdentity.authenticated`` is ``Literal[False]``. A source claiming to
  be authenticated fails validation rather than being constructed, because
  PACTRA has no cryptographic authentication for these channels (KL-05). Input
  authority is therefore always at or below ``AGENT_PROPOSAL``, which is what
  makes ``authority(output) <= authority(input)`` provable rather than hoped.
* ``CandidateOperationType`` has **no privileged member**. A tool call named
  ``payment.execute`` is not "denied" by a check that could be deleted — there
  is no canonical operation it maps to, so it cannot be represented.
* ``CandidateAuthorizationRequest`` has no nonce, no transaction digest, no
  authorization id, no status and no ``consumed_at``. It is a REQUEST. An
  external authorization representation cannot become a PACTRA authorization
  artifact, because the type that would carry one does not exist here.
* ``CandidateCommerceOffer`` carries no ``MerchantContext`` and no trust field.
  Turning one into a ``ProvenancedOffer`` requires a caller to supply a
  transport-authenticated context, so an adapter cannot assign merchant trust.

Authority and trust reuse the kernel's own ``AuthorityLevel`` / ``TrustLevel``
rather than a parallel adapter vocabulary. Two trust scales are two chances to
map one onto the other slightly wrong, in a direction somebody benefits from.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Literal

from packages.schemas.canonical import canonical_digest
from packages.schemas.capability import Capability
from packages.schemas.domain import ClaimValue, RawMerchantOffer, utcnow
from packages.schemas.provenance import AuthorityLevel, ProvenanceMeta, TrustLevel
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

# --------------------------------------------------------------------------- #
# Families
# --------------------------------------------------------------------------- #


class AdapterFamily(str, Enum):
    """The five integration layers, kept apart on purpose.

    MCP, ACP, AP2, x402 and Razorpay are not interchangeable, and the v1 design
    that treated them as one thing is the mistake this phase corrects. A family
    is declared, never inferred, and ``AdapterRegistry.get`` requires the caller
    to state which one it expects.

    ``PAYMENT_RAIL`` and ``AGENT_COMMUNICATION`` are declared but hold no
    translating adapter, for two different reasons:

    * A payment rail EXECUTES. Its boundary is the Phase 4 ``PaymentProvider``
      protocol, resolved through ``services.payment_executor.registry`` and
      reachable only from the payment executor. Registering one here would put
      an execution adapter in a registry whose entries are pure functions.
    * No protocol requirement in this repository justifies an agent-to-agent
      family yet, and an empty base class is decoration. See
      ``services/adapters/agents/__init__.py``.
    """

    COMMERCE = "COMMERCE"
    PAYMENT_AUTHORIZATION = "PAYMENT_AUTHORIZATION"
    TOOL = "TOOL"
    AGENT_COMMUNICATION = "AGENT_COMMUNICATION"
    PAYMENT_RAIL = "PAYMENT_RAIL"

    @property
    def display_name(self) -> str:
        """The name used in prose and in the protocol support matrix."""
        return _FAMILY_DISPLAY_NAMES[self]


_FAMILY_DISPLAY_NAMES: dict[AdapterFamily, str] = {
    AdapterFamily.COMMERCE: "CommerceAdapter",
    AdapterFamily.PAYMENT_AUTHORIZATION: "PaymentAuthorizationAdapter",
    AdapterFamily.TOOL: "ToolAdapter",
    AdapterFamily.AGENT_COMMUNICATION: "AgentCommunicationAdapter",
    AdapterFamily.PAYMENT_RAIL: "PaymentRailAdapter",
}

#: Families that may hold an entry in the TRANSLATING adapter registry. A
#: registration into any other family is refused rather than silently accepted,
#: so the cross-family rule is enforced at registration time and again at
#: resolution time.
TRANSLATING_FAMILIES = frozenset(
    {
        AdapterFamily.COMMERCE,
        AdapterFamily.PAYMENT_AUTHORIZATION,
        AdapterFamily.TOOL,
    }
)

#: The highest authority any translating adapter may attach to a value it
#: produces. Deliberately ``AGENT_PROPOSAL``: an adapter's input is an external
#: proposal, and no amount of successful parsing turns a proposal into a policy.
MAX_ADAPTER_AUTHORITY = AuthorityLevel.AGENT_PROPOSAL


class SupportStatus(str, Enum):
    """The only four things PACTRA may say about a protocol.

    There is deliberately no ``SUPPORTED``. "Supported" is the word that lets a
    README claim an integration a repository does not contain; each of these
    four says something a reader can go and check.
    """

    IMPLEMENTED = "IMPLEMENTED"
    PARTIAL = "PARTIAL"
    PLANNED = "PLANNED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


# --------------------------------------------------------------------------- #
# Source identity
# --------------------------------------------------------------------------- #


class SourceIdentity(BaseModel):
    """Who the payload SAYS it is. Never who it has been proven to be.

    ``authenticated`` is a ``Literal[False]`` rather than a boolean anybody
    could set, and that is the honest position: PACTRA authenticates merchants
    by server-side adapter registration and authenticates nothing at all on a
    protocol channel. There is no mutual TLS, no signed assertion, and no
    verifier (KL-05). A field that could be ``True`` would be a field somebody
    eventually sets to ``True``.

    The consequence is load-bearing rather than cosmetic. Because the input to
    every translation is unauthenticated, its authority is at most
    ``AGENT_PROPOSAL``, so an adapter capped at ``AGENT_PROPOSAL`` cannot raise
    authority even in principle.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    #: What the caller claims to be. Carried so a claim stays visible and
    #: auditable, exactly as ``claimed_merchant_id`` is on a merchant offer.
    claimed_id: str = Field(min_length=1, max_length=200)
    #: Transport the payload arrived on, named by the trusted caller rather than
    #: read out of the payload.
    channel: str = Field(min_length=1, max_length=120)
    authenticated: Literal[False] = False

    @property
    def trust(self) -> TrustLevel:
        return TrustLevel.UNTRUSTED

    @property
    def authority(self) -> AuthorityLevel:
        return AuthorityLevel.AGENT_PROPOSAL


# --------------------------------------------------------------------------- #
# Descriptor — server-owned adapter identity
# --------------------------------------------------------------------------- #


class AdapterDescriptor(BaseModel):
    """The server's statement of what an adapter is.

    Frozen and held in the server-owned registry. Nothing in a payload
    contributes to it: an ``AdapterEnvelope`` copies ``adapter_id``,
    ``protocol_name``, ``protocol_version`` and ``adapter_version`` from HERE,
    which is why a caller cannot label its own request
    ``adapter_id="trusted_mcp_adapter"`` and acquire anything.

    ``supported_protocol_versions`` is exhaustive and closed. A version outside
    it is refused rather than assumed compatible — including a NEWER one, which
    is the case people are tempted to wave through.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    adapter_id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9._-]+$")
    family: AdapterFamily
    protocol_name: str = Field(min_length=1, max_length=80)
    #: The version this adapter reports as its primary target. Always a member
    #: of ``supported_protocol_versions``.
    protocol_version: str = Field(min_length=1, max_length=40)
    supported_protocol_versions: tuple[str, ...] = Field(min_length=1)
    adapter_version: str = Field(min_length=1, max_length=40)
    status: SupportStatus
    #: Ceiling on the authority any value this adapter emits may carry.
    emits_authority: AuthorityLevel = AuthorityLevel.AGENT_PROPOSAL
    emits_trust: TrustLevel = TrustLevel.UNTRUSTED
    #: One sentence naming exactly what the adapter translates, used verbatim by
    #: ``--describe`` and by the support matrix.
    summary: str = Field(min_length=10, max_length=400)

    @model_validator(mode="after")
    def _check_ceilings(self) -> AdapterDescriptor:
        if self.emits_authority > MAX_ADAPTER_AUTHORITY:
            raise ValueError(
                f"adapter {self.adapter_id!r} declares emits_authority "
                f"{self.emits_authority.name}, above the adapter ceiling "
                f"{MAX_ADAPTER_AUTHORITY.name}"
            )
        if self.emits_trust is not TrustLevel.UNTRUSTED:
            raise ValueError(
                f"adapter {self.adapter_id!r} declares emits_trust "
                f"{self.emits_trust.value}; a translating adapter emits untrusted values only"
            )
        if self.protocol_version not in self.supported_protocol_versions:
            raise ValueError(
                f"adapter {self.adapter_id!r} names primary protocol version "
                f"{self.protocol_version!r}, which is not in its supported set"
            )
        return self

    def supports(self, protocol_version: str) -> bool:
        return protocol_version in self.supported_protocol_versions


# --------------------------------------------------------------------------- #
# Canonical payloads, one per translating family
# --------------------------------------------------------------------------- #


class CandidateCommerceOffer(BaseModel):
    """One offer as an external commerce source described it.

    WHAT IS NOT HERE IS THE POINT. There is no ``merchant_trust``, no
    ``merchant_name``, and no ``MerchantContext``. Becoming a kernel
    ``ProvenancedOffer`` requires ``ingest_merchant_offer(raw, context)``, and
    the context comes from ``MerchantTransport`` — a component this package
    cannot reach. So a commerce adapter cannot assign server-owned merchant
    trust: not because it is forbidden to, but because it holds nothing to
    assign it from.

    ``claimed_merchant_id`` mirrors the Phase 2 treatment exactly: a claim is
    kept, visible, and checked against an authenticated identity later. It is
    never folded to lowercase — identity comparison is exact, so a case variant
    simply fails to match rather than quietly matching.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    claimed_merchant_id: str = Field(min_length=1, max_length=120)
    #: The untrusted payload, through PACTRA's existing strict merchant schema.
    offer: RawMerchantOffer
    #: Payload keys the protocol does not define, kept so nothing is lost and a
    #: reader can see what was sent. Never canonical, never security state.
    untrusted_metadata: dict[str, ClaimValue] = Field(default_factory=dict)


class CandidateCommerceCatalog(BaseModel):
    """A whole external catalog response, normalized offer by offer.

    ``untrusted_metadata`` exists at BOTH levels of the document, and that
    uniformity is deliberate. Preserving an unknown field on an offer while
    silently dropping one on the envelope around it would mean the same key had
    two different fates depending on where a sender put it — and the dropped
    half would be invisible to every reader.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    claimed_merchant_id: str = Field(min_length=1, max_length=120)
    offers: tuple[CandidateCommerceOffer, ...] = Field(default_factory=tuple)
    untrusted_metadata: dict[str, ClaimValue] = Field(default_factory=dict)


class CandidateOperationType(str, Enum):
    """The closed set of operations an external tool call may name.

    READ THE ABSENCES. There is no ``PAYMENT_EXECUTE``, no ``REFUND_EXECUTE``,
    no ``POLICY_MODIFY``, no ``AUTHORIZATION_ISSUE`` and no ``MERCHANT_MODIFY``.
    A tool adapter does not "refuse" a privileged tool call; it has no canonical
    value to translate one into, so the refusal cannot be configured away, and
    adding one would require adding an enum member in a diff a reviewer sees.
    """

    CATALOG_SEARCH = "catalog.search"
    MERCHANT_DISCOVER = "merchant.discover"
    OFFER_REQUEST = "offer.request"
    OFFER_RANK = "offer.rank"
    PURCHASE_PROPOSE = "purchase.propose"


#: Server-owned operation -> capability table. Every entry is a NON-PRIVILEGED
#: capability that ``buyer-agent`` already holds, so translating a tool call
#: grants nothing the buyer agent did not already have.
#: ``tests/test_adapter_tools_mcp.py`` asserts this map's range is disjoint from
#: the privileged set, which is what makes the guarantee checkable rather than
#: asserted.
OPERATION_CAPABILITY: dict[CandidateOperationType, Capability] = {
    CandidateOperationType.CATALOG_SEARCH: Capability.CATALOG_READ,
    CandidateOperationType.MERCHANT_DISCOVER: Capability.MERCHANT_DISCOVER,
    CandidateOperationType.OFFER_REQUEST: Capability.OFFER_REQUEST,
    CandidateOperationType.OFFER_RANK: Capability.OFFER_RANK,
    CandidateOperationType.PURCHASE_PROPOSE: Capability.PAYMENT_PROPOSE,
}

#: Capabilities no adapter-originated operation may ever require. Held here as
#: data so a test can assert the disjointness rather than a reader having to
#: notice it.
PRIVILEGED_CAPABILITIES = frozenset(
    {
        Capability.PAYMENT_EXECUTE,
        Capability.REFUND_EXECUTE,
        Capability.POLICY_MODIFY,
        Capability.AUTHORIZATION_ISSUE,
        Capability.MERCHANT_MODIFY,
    }
)


class CandidateOperation(BaseModel):
    """A tool call translated into something PACTRA can reason about.

    ``candidate`` is a ``Literal[True]``, the same device Phase 7 uses for
    ``RiskAssessment.advisory``: an object asserting it is already authorized
    fails validation instead of being constructed.

    ``required_capability`` is a PROPERTY read from the server-owned table, not
    a field. A field would be a place a payload could write.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate: Literal[True] = True
    operation: CandidateOperationType
    #: The tool name the caller actually used, kept verbatim so an audit or a
    #: report shows what was asked for rather than what it was mapped to.
    claimed_tool_name: str = Field(min_length=1, max_length=200)
    #: Untrusted arguments. JSON-safe scalars only — the same closed union
    #: ``RawMerchantOffer.claims`` uses, because these values are equally likely
    #: to end up serialized into a report.
    arguments: dict[str, ClaimValue] = Field(default_factory=dict)

    @property
    def required_capability(self) -> Capability:
        return OPERATION_CAPABILITY[self.operation]


class CandidateAuthorizationRequest(BaseModel):
    """An external authorization INTENTION. Not an authorization.

    ``EXTERNAL AUTHORIZATION TOKEN != PACTRA AUTHORIZATION``, and this type is
    where that is made structural. Compare it to
    ``packages.schemas.authorization.Authorization``: there is no ``nonce``, no
    ``transaction_digest``, no ``authorization_id``, no ``status``, no
    ``consumed_at``, no ``binding_version``. Nothing here can be consumed,
    because a consumable artifact is a different type that only
    ``issue_authorization`` can mint, under a capability this package cannot
    reach.

    ``external_authorization_reference`` is an opaque correlation string. PACTRA
    does NOT verify it and holds no verifier that could: there is no user
    signing and no signature verification anywhere in the system (KL-04). It is
    carried so a caller can correlate its own records, and a warning saying it
    was not verified travels on every envelope that contains one.

    Amounts are ``StrictInt``. A protocol boundary is exactly where lax
    coercion turns ``"3799"`` and ``3799.0`` into money, and binary floats have
    no canonical decimal form — which is why the canonical encoder rejects them
    outright.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate: Literal[True] = True
    #: Present when the external caller is continuing an existing PACTRA
    #: mission. Never a grant: the mission's own state decides what may happen.
    mission_id: uuid.UUID | None = None
    claimed_merchant_id: str = Field(min_length=1, max_length=120)
    claimed_product_id: str = Field(min_length=1, max_length=120)
    claimed_quantity: StrictInt = Field(ge=1, le=100)
    claimed_amount_inr: StrictInt = Field(ge=1)
    claimed_currency: str = Field(min_length=3, max_length=3)
    claimed_expires_at: datetime | None = None
    external_authorization_reference: str | None = Field(default=None, max_length=400)
    untrusted_metadata: dict[str, ClaimValue] = Field(default_factory=dict)

    @field_validator("claimed_currency")
    @classmethod
    def _upper_currency(cls, v: str) -> str:
        """Currency is case-folded, matching ``MissionConstraints`` and
        ``BoundTransaction``. Merchant and product ids deliberately are NOT:
        identity is compared exactly, so a case variant must fail to match
        rather than be normalized into matching."""
        return v.upper()

    @model_validator(mode="after")
    def _expiry_is_timezone_aware(self) -> CandidateAuthorizationRequest:
        if self.claimed_expires_at is not None:
            offset = self.claimed_expires_at.utcoffset()
            if self.claimed_expires_at.tzinfo is None or offset is None:
                raise ValueError(
                    "claimed_expires_at must be timezone-aware; "
                    "a naive expiry has no single instant"
                )
        return self


#: Everything a translating adapter may put in an envelope. A union rather than
#: ``Any``: an envelope whose payload could be anything is an envelope nothing
#: downstream can branch on safely.
CanonicalPayload = (
    CandidateCommerceCatalog
    | CandidateCommerceOffer
    | CandidateOperation
    | CandidateAuthorizationRequest
)

#: Which payload types each family is permitted to emit. Checked by
#: ``translate`` after the adapter returns, so a tool adapter cannot hand back
#: an authorization request and have it travel under a TOOL envelope.
FAMILY_PAYLOAD_TYPES: dict[AdapterFamily, tuple[type, ...]] = {
    AdapterFamily.COMMERCE: (CandidateCommerceCatalog, CandidateCommerceOffer),
    AdapterFamily.TOOL: (CandidateOperation,),
    AdapterFamily.PAYMENT_AUTHORIZATION: (CandidateAuthorizationRequest,),
}


# --------------------------------------------------------------------------- #
# Warnings
# --------------------------------------------------------------------------- #


class AdapterWarningCode(str, Enum):
    """Things a reader must know about a translation that still succeeded."""

    CLAIMED_IDENTITY_NOT_AUTHENTICATED = "CLAIMED_IDENTITY_NOT_AUTHENTICATED"
    EXTERNAL_AUTHORIZATION_REFERENCE_NOT_VERIFIED = "EXTERNAL_AUTHORIZATION_REFERENCE_NOT_VERIFIED"
    UNKNOWN_FIELDS_KEPT_AS_UNTRUSTED_METADATA = "UNKNOWN_FIELDS_KEPT_AS_UNTRUSTED_METADATA"
    MERCHANT_TRUST_NOT_ASSIGNED_BY_ADAPTER = "MERCHANT_TRUST_NOT_ASSIGNED_BY_ADAPTER"


class AdapterWarning(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: AdapterWarningCode
    detail: str = Field(min_length=1, max_length=400)


# --------------------------------------------------------------------------- #
# The envelope
# --------------------------------------------------------------------------- #

#: Domain separator for the envelope's canonical fingerprint. Never reused for a
#: transaction digest: a fingerprint computed for one purpose must not be
#: replayable as a digest for another.
ENVELOPE_FINGERPRINT_DOMAIN = "pactra-adapter-envelope-v1"


class AdapterEnvelope(BaseModel):
    """What a translation produced, and everything needed to distrust it.

    Identity fields come from the server-owned ``AdapterDescriptor``, never from
    the payload. ``raw_reference`` is a SHA-256 of the raw bytes plus their
    length — enough to correlate an envelope with the delivery that produced it,
    and deliberately not a copy of the payload, which may carry anything an
    external party chose to send.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    # --- server-owned identity ---
    adapter_id: str
    adapter_family: AdapterFamily
    protocol_name: str
    protocol_version: str
    adapter_version: str

    # --- the claim, kept as a claim ---
    source_identity: SourceIdentity
    source_trust: TrustLevel
    source_authority: AuthorityLevel

    received_at: datetime = Field(default_factory=utcnow)
    #: "sha256:<hex>" over the exact bytes received. Safe metadata, not content.
    raw_reference: str = Field(min_length=8, max_length=100)
    raw_byte_length: int = Field(ge=0)

    canonical_payload: CanonicalPayload
    #: Per-field provenance for every canonical value, in the kernel's own
    #: vocabulary. ``translate`` checks this two ways before the envelope is
    #: returned: every entry against the descriptor's authority ceiling and its
    #: taint, and the KEY SET against ``required_provenance_keys``, so an
    #: adapter can neither mark a value wrongly nor leave one unmarked.
    provenance: dict[str, ProvenanceMeta] = Field(default_factory=dict)
    #: Always True for a translating adapter. A parser does not sanitize
    #: authority, so nothing that arrives untrusted leaves trusted.
    taint: Literal[True] = True
    warnings: tuple[AdapterWarning, ...] = Field(default_factory=tuple)

    def canonical_fingerprint(self) -> str:
        """A deterministic digest of what this translation MEANS.

        Deliberately excludes ``received_at`` and ``raw_reference``: the first
        is a clock read and the second is a property of the delivery, and
        neither is part of the translation's meaning. This is what the
        determinism contract compares, so "the same adapter and the same
        canonical input translate identically" is a checkable statement rather
        than an aspiration.

        The payload is serialized in JSON mode and hashed as one canonical
        string. It is NOT the transaction encoder's per-field type tagging —
        this fingerprint is a test and diagnostic handle, and nothing in the
        kernel makes a decision from it.
        """
        return canonical_digest(
            ENVELOPE_FINGERPRINT_DOMAIN,
            {
                "adapter_id": self.adapter_id,
                "adapter_family": self.adapter_family.value,
                "protocol_name": self.protocol_name,
                "protocol_version": self.protocol_version,
                "adapter_version": self.adapter_version,
                "claimed_id": self.source_identity.claimed_id,
                "channel": self.source_identity.channel,
                "payload": self.canonical_payload.model_dump_json(),
                "provenance": ",".join(
                    f"{name}={meta.source}|{meta.authority.name}|"
                    f"{meta.trust.value}|{int(meta.tainted)}"
                    for name, meta in sorted(self.provenance.items())
                ),
                "warnings": ",".join(sorted(w.code.value for w in self.warnings)),
            },
        )


# --------------------------------------------------------------------------- #
# Provenance completeness — server-owned, so an adapter cannot under-report
# --------------------------------------------------------------------------- #


def _metadata_key(prefix: str) -> str:
    return f"{prefix}untrusted_metadata" if prefix else "untrusted_metadata"


def _offer_keys(offer: CandidateCommerceOffer, prefix: str) -> set[str]:
    """Provenance keys one candidate offer must carry.

    Names the RawMerchantOffer's own fields directly under the offer's prefix —
    ``offers[0].price`` rather than ``offers[0].offer.price`` — because the
    wrapper is PACTRA's, not the sender's, and a reader tracing a value back to
    the wire should see the path the wire used.
    """
    keys = {f"{prefix}{name}" for name in type(offer.offer).model_fields}
    if offer.untrusted_metadata:
        keys.add(_metadata_key(prefix))
    return keys


def required_provenance_keys(payload: object) -> frozenset[str]:
    """Every canonical value that came off the wire, named.

    Takes ``object`` rather than ``CanonicalPayload`` deliberately. The caller
    is ``_check_result``, which has already refused anything outside its
    family's permitted types — but it does so against a runtime tuple, so a
    narrower static type would be a promise the call site cannot actually make.
    Widening the parameter keeps the final ``raise`` reachable, so an
    unrecognised payload type is refused at RUNTIME rather than merely flagged
    in a type check somebody can silence with a cast.

    SERVER-OWNED AND CHECKED AFTER THE ADAPTER RETURNS, for the reason every
    other check in ``translate`` is: an adapter that decides for itself which of
    its output deserves provenance is an adapter that can leave the
    security-relevant half unmarked. ``AdapterEnvelope.provenance`` documents
    itself as per-field provenance for every canonical value, and this is what
    makes that sentence enforced rather than aspirational.

    ``candidate`` is excluded: it is a ``Literal[True]`` the SERVER sets, not a
    value anybody sent. A ``None`` optional is excluded because nothing arrived
    to have a provenance, and an empty ``untrusted_metadata`` likewise — a key
    demanding provenance for a value that does not exist would push adapters
    into inventing entries, which is the opposite of the point.
    """
    if isinstance(payload, CandidateCommerceCatalog):
        keys = {"claimed_merchant_id"}
        for index, offer in enumerate(payload.offers):
            keys |= _offer_keys(offer, f"offers[{index}].")
        if payload.untrusted_metadata:
            keys.add(_metadata_key(""))
        return frozenset(keys)

    if isinstance(payload, CandidateCommerceOffer):
        return frozenset(_offer_keys(payload, "") | {"claimed_merchant_id"})

    if isinstance(payload, CandidateOperation):
        return frozenset(
            {"operation", "claimed_tool_name"} | {f"arguments.{name}" for name in payload.arguments}
        )

    if isinstance(payload, CandidateAuthorizationRequest):
        keys = {
            "claimed_merchant_id",
            "claimed_product_id",
            "claimed_quantity",
            "claimed_amount_inr",
            "claimed_currency",
        }
        for optional in ("mission_id", "claimed_expires_at", "external_authorization_reference"):
            if getattr(payload, optional) is not None:
                keys.add(optional)
        if payload.untrusted_metadata:
            keys.add(_metadata_key(""))
        return frozenset(keys)

    # Unreachable while CanonicalPayload is the closed union above. Raising
    # rather than returning an empty set means a payload type added without a
    # completeness rule fails loudly instead of silently requiring nothing.
    raise TypeError(
        f"no provenance-completeness rule for {type(payload).__name__}; "
        "a canonical payload type without one would require no provenance at all"
    )
