"""The family contracts, applied to EVERY registered adapter.

WHY THESE ARE PARAMETRIZED OVER THE REGISTRY RATHER THAN WRITTEN PER ADAPTER
----------------------------------------------------------------------------
A contract asserted about the three adapters that exist today is a contract the
fourth one silently escapes. Every test here reads
``load_registry().list()`` and runs against whatever is registered, so adding an
adapter without satisfying the contract fails the suite rather than passing it
by omission.

Each adapter contributes its own well-formed fixture through ``VALID_FIXTURES``.
An adapter with no fixture fails ``test_every_registered_adapter_has_a_fixture``,
so a new adapter cannot opt out of the contract by not providing one.

THE CONTRACTS
    deterministic translation          same input -> same canonical fingerprint
    source identity preserved          the claim is kept, and stays a claim
    taint preserved                    every value untrusted and tainted
    authority never increased          output <= descriptor ceiling <= AGENT_PROPOSAL
    caller capability claims ignored   reserved fields refused, server set unchanged
    malformed input rejected           before any value reaches a domain model
    unsupported version rejected       never reinterpreted
    no payment side effect             translate takes no session
    no authorization issuance          no artifact field exists to fill
    no policy mutation                 protected fields refused at the top level
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone

import pytest
from packages.schemas.provenance import AuthorityLevel, TrustLevel
from services.adapters.errors import (
    AdapterError,
    MalformedProtocolPayload,
    ProvenanceIncomplete,
    ReservedFieldRejected,
    UnsupportedProtocolVersion,
)
from services.adapters.fields import RESERVED_SECURITY_FIELDS
from services.adapters.models import (
    FAMILY_PAYLOAD_TYPES,
    MAX_ADAPTER_AUTHORITY,
    AdapterFamily,
    SourceIdentity,
    required_provenance_keys,
)
from services.adapters.registry import load_registry
from services.adapters.translate import _check_result, translate
from services.adapters.translation import TranslationResult

SOURCE = SourceIdentity(claimed_id="contract-caller", channel="pytest")
FIXED_RECEIVED_AT = datetime(2026, 6, 1, 9, 0, 0, tzinfo=timezone.utc)

MCP = "mcp.tools-call.v1"
COMMERCE = "pactra.commerce.v1"
INTENT = "pactra.authorization-intent.v1"


def mcp_fixture() -> dict:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "pactra.offer.request",
            "arguments": {"category": "wireless_earbuds", "quantity": 1},
        },
    }


def commerce_fixture() -> dict:
    return {
        "protocol": "pactra.commerce",
        "merchant_id": "merchant_a",
        "offers": [
            {
                "merchant_id": "merchant_a",
                "product_id": "aur-eb-01",
                "title": "Aurora SoundCore Wireless Earbuds",
                "description": "Premium ANC earbuds.",
                "price": 4299,
                "currency": "INR",
                "rating": 4.6,
                "in_stock": True,
                "offered_at": "2026-01-01T12:00:00+00:00",
            }
        ],
    }


def intent_fixture() -> dict:
    return {
        "protocol": "pactra.authorization-intent",
        "merchant_id": "merchant_a",
        "product_id": "P1",
        "quantity": 1,
        "amount_inr": 3799,
        "currency": "INR",
        "expires_at": "2030-01-01T12:00:00+00:00",
    }


#: adapter id -> (family, protocol version, well-formed payload factory, the
#: place a hostile top-level key would be inserted).
VALID_FIXTURES: dict[str, tuple] = {
    MCP: (AdapterFamily.TOOL, "2025-06-18", mcp_fixture),
    COMMERCE: (AdapterFamily.COMMERCE, "1.0", commerce_fixture),
    INTENT: (AdapterFamily.PAYMENT_AUTHORIZATION, "1.0", intent_fixture),
}

ADAPTER_IDS = sorted(VALID_FIXTURES)


def translate_fixture(adapter_id: str, payload=None, *, version: str | None = None):
    family, default_version, factory = VALID_FIXTURES[adapter_id]
    return translate(
        adapter_id,
        family=family,
        protocol_version=default_version if version is None else version,
        payload=factory() if payload is None else payload,
        source=SOURCE,
        received_at=FIXED_RECEIVED_AT,
    )


def hostile_variants(adapter_id: str, key: str, value=999999) -> list[dict]:
    """The same hostile key inserted everywhere this protocol accepts keys."""
    _, _, factory = VALID_FIXTURES[adapter_id]
    variants = []
    top = factory()
    top[key] = value
    variants.append(top)
    if adapter_id == MCP:
        params = factory()
        params["params"]["arguments"][key] = value
        variants.append(params)
    if adapter_id == COMMERCE:
        offer = factory()
        offer["offers"][0][key] = value
        variants.append(offer)
    return variants


# --------------------------------------------------------------------------- #
# The registry and the fixture table must not drift apart
# --------------------------------------------------------------------------- #
def test_every_registered_adapter_has_a_fixture():
    """An adapter cannot escape these contracts by providing no fixture."""
    registered = set(load_registry().ids())
    assert registered == set(VALID_FIXTURES), (
        f"registered but unconstrained: {sorted(registered - set(VALID_FIXTURES))}; "
        f"constrained but unregistered: {sorted(set(VALID_FIXTURES) - registered)}"
    )


# --------------------------------------------------------------------------- #
# Contract: deterministic translation
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("adapter_id", ADAPTER_IDS)
def test_the_same_input_translates_deterministically(adapter_id):
    first = translate_fixture(adapter_id)
    second = translate_fixture(adapter_id)
    assert first.canonical_fingerprint() == second.canonical_fingerprint()
    assert first.canonical_payload == second.canonical_payload
    assert first.provenance == second.provenance
    assert first.raw_reference == second.raw_reference


@pytest.mark.parametrize("adapter_id", ADAPTER_IDS)
def test_key_order_does_not_change_the_canonical_result(adapter_id):
    """Two byte-orderings of the same document mean the same thing.

    The fingerprint covers MEANING, so it must not move when a sender happens to
    serialize its keys differently.
    """
    _, _, factory = VALID_FIXTURES[adapter_id]
    payload = factory()
    reordered = {key: copy.deepcopy(payload[key]) for key in reversed(list(payload))}
    assert translate_fixture(adapter_id, payload).canonical_fingerprint() == (
        translate_fixture(adapter_id, reordered).canonical_fingerprint()
    )


@pytest.mark.parametrize("adapter_id", ADAPTER_IDS)
def test_the_fingerprint_does_not_depend_on_the_clock(adapter_id):
    """``received_at`` is a property of the delivery, not of the translation."""
    family, version, factory = VALID_FIXTURES[adapter_id]
    early = translate(
        adapter_id,
        family=family,
        protocol_version=version,
        payload=factory(),
        source=SOURCE,
        received_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    late = translate(
        adapter_id,
        family=family,
        protocol_version=version,
        payload=factory(),
        source=SOURCE,
        received_at=datetime(2027, 12, 31, tzinfo=timezone.utc),
    )
    assert early.received_at != late.received_at
    assert early.canonical_fingerprint() == late.canonical_fingerprint()


@pytest.mark.parametrize("adapter_id", ADAPTER_IDS)
def test_a_different_payload_produces_a_different_fingerprint(adapter_id):
    """A fingerprint that never moved would be a fingerprint of nothing."""
    baseline = translate_fixture(adapter_id).canonical_fingerprint()
    changed: dict
    if adapter_id == INTENT:
        changed = {**intent_fixture(), "amount_inr": 4399}
    elif adapter_id == MCP:
        changed = mcp_fixture()
        changed["params"]["arguments"]["category"] = "headphones"
    else:
        changed = commerce_fixture()
        changed["offers"][0]["price"] = 3999
    assert translate_fixture(adapter_id, changed).canonical_fingerprint() != baseline


@pytest.mark.parametrize("adapter_id", ADAPTER_IDS)
def test_an_unknown_field_is_never_silently_ignored(adapter_id):
    """An unknown field either CHANGES the canonical result or is REFUSED.

    Both outcomes are honest and the adapters make the choice per protocol
    shape: an extensible content document (a catalog, an intent) preserves an
    unknown key as untrusted metadata, while a fixed-shape JSON-RPC envelope
    refuses one as a malformed message. What neither may do is ignore it — a
    dropped field is invisible to every reader, and a key with two different
    fates depending on where a sender put it is a key nobody can reason about.

    Both halves were caught here during construction: a top-level catalog key
    used to vanish, and an undefined JSON-RPC envelope member used to be
    accepted and dropped.
    """
    baseline = translate_fixture(adapter_id).canonical_fingerprint()
    for payload in hostile_variants(adapter_id, "unremarkable_extra_field", "x"):
        try:
            fingerprint = translate_fixture(adapter_id, payload).canonical_fingerprint()
        except MalformedProtocolPayload:
            continue  # refused: also not ignored
        assert fingerprint != baseline, "an unknown field was silently dropped"


# --------------------------------------------------------------------------- #
# Contract: source identity preserved, and preserved AS A CLAIM
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("adapter_id", ADAPTER_IDS)
def test_the_claimed_source_is_kept_and_stays_a_claim(adapter_id):
    envelope = translate_fixture(adapter_id)
    assert envelope.source_identity.claimed_id == SOURCE.claimed_id
    assert envelope.source_identity.channel == SOURCE.channel
    assert envelope.source_identity.authenticated is False
    assert envelope.source_trust is TrustLevel.UNTRUSTED
    assert envelope.source_authority is AuthorityLevel.AGENT_PROPOSAL


@pytest.mark.parametrize("adapter_id", ADAPTER_IDS)
def test_provenance_names_the_registered_adapter_and_the_claim(adapter_id):
    envelope = translate_fixture(adapter_id)
    assert envelope.provenance
    for meta in envelope.provenance.values():
        assert meta.source.startswith(f"adapter:{adapter_id}:")
        # The claimed id is marked as a claim, so nothing reading the string can
        # mistake it for an authenticated identity.
        assert ":claim:" in meta.source


@pytest.mark.parametrize("adapter_id", ADAPTER_IDS)
def test_envelope_identity_comes_from_the_descriptor_not_the_payload(adapter_id):
    descriptor = load_registry().describe(adapter_id)
    envelope = translate_fixture(adapter_id)
    assert envelope.adapter_id == descriptor.adapter_id
    assert envelope.adapter_family is descriptor.family
    assert envelope.protocol_name == descriptor.protocol_name
    assert envelope.adapter_version == descriptor.adapter_version


# --------------------------------------------------------------------------- #
# Contract: taint preserved, authority never increased
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("adapter_id", ADAPTER_IDS)
def test_every_translated_value_stays_tainted_and_untrusted(adapter_id):
    envelope = translate_fixture(adapter_id)
    assert envelope.taint is True
    for name, meta in envelope.provenance.items():
        assert meta.tainted is True, name
        assert meta.trust is TrustLevel.UNTRUSTED, name
        # Translation IS a transformation, and taint is sticky through it.
        assert meta.transformed is True, name


@pytest.mark.parametrize("adapter_id", ADAPTER_IDS)
def test_every_canonical_value_carries_provenance(adapter_id):
    """Per-entry validity is not the same property as coverage.

    ``test_every_translated_value_stays_tainted_and_untrusted`` iterates over
    the entries an adapter CHOSE to emit, so an adapter that marked six fields
    and left the merchant identity claim unmarked would pass it — and the values
    a reader most needs to distrust are exactly the ones an adapter is most
    likely to forget. The required set is derived from the payload by a
    server-owned rule, so this cannot be satisfied by narrowing the obligation.
    """
    envelope = translate_fixture(adapter_id)
    required = required_provenance_keys(envelope.canonical_payload)
    assert required, adapter_id
    assert not (required - set(envelope.provenance)), (
        f"{adapter_id} emitted canonical values with no provenance: "
        f"{sorted(required - set(envelope.provenance))}"
    )


@pytest.mark.parametrize("adapter_id", ADAPTER_IDS)
def test_optional_and_metadata_values_carry_provenance_once_present(adapter_id):
    """Coverage has to hold for the fields a minimal fixture never exercises.

    An unknown field and an external authorization reference are both absent
    from the well-formed fixtures, so a rule checked only against those would
    never see them. They are also two of the values most worth marking: one is
    protocol-undefined, the other is an unverifiable claim of approval.
    """
    _, _, factory = VALID_FIXTURES[adapter_id]
    payload = factory()
    if adapter_id == MCP:
        payload["params"]["arguments"]["unknown_extra"] = "kept-as-metadata"
    elif adapter_id == COMMERCE:
        payload["offers"][0]["unknown_extra"] = "kept-as-metadata"
        payload["unknown_catalog_extra"] = "kept-as-metadata"
    else:
        payload["unknown_extra"] = "kept-as-metadata"
        payload["external_authorization_reference"] = "ext-ref-not-verified"

    envelope = translate_fixture(adapter_id, payload)
    required = required_provenance_keys(envelope.canonical_payload)
    assert not (required - set(envelope.provenance)), (
        f"{adapter_id} left an optional or metadata value unmarked: "
        f"{sorted(required - set(envelope.provenance))}"
    )


@pytest.mark.parametrize("adapter_id", ADAPTER_IDS)
def test_an_adapter_that_under_reports_provenance_is_refused(adapter_id):
    """The check runs AFTER the adapter returns, so it cannot be opted out of.

    Driven through ``_check_result`` directly because the process registry is
    sealed: a deliberately under-reporting adapter cannot be registered, which
    is itself the point — this proves the guard would catch one if a future edit
    added it to the built-in list.
    """
    envelope = translate_fixture(adapter_id)
    required = sorted(required_provenance_keys(envelope.canonical_payload))
    if len(required) == 1:
        pytest.skip("a single-field payload cannot under-report")
    starved = TranslationResult(
        canonical_payload=envelope.canonical_payload,
        provenance={required[0]: envelope.provenance[required[0]]},
        warnings=(),
    )
    with pytest.raises(ProvenanceIncomplete) as exc:
        _check_result(
            adapter_id=adapter_id,
            family=envelope.adapter_family,
            max_authority=MAX_ADAPTER_AUTHORITY,
            result=starved,
        )
    assert exc.value.reason_code == "ADAPTER_PROVENANCE_INCOMPLETE"


@pytest.mark.parametrize("adapter_id", ADAPTER_IDS)
def test_authority_never_exceeds_the_input_or_the_ceiling(adapter_id):
    descriptor = load_registry().describe(adapter_id)
    envelope = translate_fixture(adapter_id)
    for name, meta in envelope.provenance.items():
        assert meta.authority <= descriptor.emits_authority, name
        assert meta.authority <= MAX_ADAPTER_AUTHORITY, name
        assert meta.authority <= envelope.source_authority, name


@pytest.mark.parametrize("adapter_id", ADAPTER_IDS)
def test_the_payload_type_matches_the_declared_family(adapter_id):
    envelope = translate_fixture(adapter_id)
    permitted = FAMILY_PAYLOAD_TYPES[envelope.adapter_family]
    assert isinstance(envelope.canonical_payload, permitted)


# --------------------------------------------------------------------------- #
# Contract: caller capability and security claims are ignored
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("adapter_id", ADAPTER_IDS)
@pytest.mark.parametrize(
    "key",
    ["capabilities", "principal", "authority", "trusted", "policy_override", "merchant_trust"],
)
def test_security_reserved_keys_are_refused_wherever_they_appear(adapter_id, key):
    for payload in hostile_variants(adapter_id, key):
        with pytest.raises(ReservedFieldRejected):
            translate_fixture(adapter_id, payload)


@pytest.mark.parametrize("adapter_id", ADAPTER_IDS)
def test_the_whole_reserved_set_is_refused(adapter_id):
    """Swept over the declared set rather than a remembered sample."""
    accepted = []
    for canonical in sorted(RESERVED_SECURITY_FIELDS):
        for payload in hostile_variants(adapter_id, canonical, "x"):
            try:
                translate_fixture(adapter_id, payload)
                accepted.append(canonical)
            except AdapterError:
                pass
    assert not accepted, f"{adapter_id} accepted reserved fields: {sorted(set(accepted))}"


@pytest.mark.parametrize("adapter_id", ADAPTER_IDS)
def test_translation_does_not_alter_server_capabilities(adapter_id):
    from services.security_kernel.capability_registry import capabilities_for

    before = {
        p: capabilities_for(p) for p in ("buyer-agent", "security-kernel", "payment-executor")
    }
    try:
        translate_fixture(adapter_id)
    except AdapterError:  # pragma: no cover - fixtures are valid
        pass
    after = {p: capabilities_for(p) for p in before}
    assert before == after


# --------------------------------------------------------------------------- #
# Contract: malformed input and unsupported versions are refused
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("adapter_id", ADAPTER_IDS)
@pytest.mark.parametrize(
    "payload",
    [b"{not json", b"[1,2,3]", b'"scalar"', b"", b"null", {"unrelated": "document"}],
)
def test_malformed_payloads_are_refused(adapter_id, payload):
    with pytest.raises(AdapterError):
        translate_fixture(adapter_id, payload)


@pytest.mark.parametrize("adapter_id", ADAPTER_IDS)
def test_an_oversize_payload_is_refused_before_parsing(adapter_id):
    from services.adapters.translate import MAX_PAYLOAD_BYTES

    with pytest.raises(MalformedProtocolPayload):
        translate_fixture(adapter_id, b"x" * (MAX_PAYLOAD_BYTES + 1))


@pytest.mark.parametrize("adapter_id", ADAPTER_IDS)
@pytest.mark.parametrize("version", ["9999-99-99", "0.0", "", "*", "latest", "2.0"])
def test_an_undeclared_protocol_version_is_refused(adapter_id, version):
    descriptor = load_registry().describe(adapter_id)
    if descriptor.supports(version):  # pragma: no cover - guards the parametrization
        pytest.skip(f"{version} is genuinely supported by {adapter_id}")
    with pytest.raises(UnsupportedProtocolVersion):
        translate_fixture(adapter_id, version=version)


@pytest.mark.parametrize("adapter_id", ADAPTER_IDS)
def test_every_declared_version_actually_works(adapter_id):
    """An adapter that refused every version would pass the test above and be
    useless. Each declared version must genuinely translate."""
    descriptor = load_registry().describe(adapter_id)
    for version in descriptor.supported_protocol_versions:
        envelope = translate_fixture(adapter_id, version=version)
        assert envelope.protocol_version == version


# --------------------------------------------------------------------------- #
# Contract: no side effects (the type signature, then the behaviour)
# --------------------------------------------------------------------------- #
def test_translate_takes_no_database_session():
    """The signature is the guarantee. There is no parameter to write through."""
    import inspect

    parameters = set(inspect.signature(translate).parameters)
    assert not (parameters & {"session", "sessionmaker", "db", "engine", "connection"})
    assert not inspect.iscoroutinefunction(translate)


@pytest.mark.parametrize("adapter_id", ADAPTER_IDS)
def test_translation_is_synchronous_all_the_way_down(adapter_id):
    """An async translate_payload could await a provider; a sync one cannot."""
    import inspect

    family, _, _ = VALID_FIXTURES[adapter_id]
    implementation = load_registry().get(adapter_id, family=family).implementation
    assert not inspect.iscoroutinefunction(implementation.translate_payload)


@pytest.mark.parametrize("adapter_id", ADAPTER_IDS)
def test_no_envelope_carries_an_authorization_or_a_payment(adapter_id):
    """The canonical payload has no field that could name either."""
    fields = set(type(translate_fixture(adapter_id).canonical_payload).model_fields)
    forbidden = {
        "authorization_id",
        "nonce",
        "transaction_digest",
        "payment_intent_id",
        "provider_payment_id",
        "idempotency_key",
        "status",
        "capability",
        "capabilities",
        "merchant_trust",
        "risk_score",
    }
    assert not (fields & forbidden), f"{adapter_id} emits {sorted(fields & forbidden)}"
