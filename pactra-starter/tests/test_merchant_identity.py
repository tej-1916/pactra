"""Merchant identity spoofing and trust forgery.

These are the Phase 2 security-correction tests. They prove that merchant
identity comes from the transport and merchant trust comes from the server-owned
registry, so a hostile merchant can neither impersonate an allowed merchant nor
award itself a trust score.
"""

import pytest
from apps.api.db.models import Offer
from packages.schemas.domain import CreateMissionRequest, EventType, RawMerchantOffer, ReasonCode
from packages.schemas.merchant import MerchantAuthMethod, MerchantIdentity
from packages.schemas.provenance import AuthorityLevel, TrustLevel
from pydantic import ValidationError
from services.agent_orchestrator.merchants.mock_merchants import (
    MockMerchantA,
    MockMerchantB,
    SpoofingMerchant,
)
from services.agent_orchestrator.merchants.transport import MerchantTransport
from services.agent_orchestrator.orchestrator import Orchestrator
from services.audit_ledger.ledger import list_events
from services.policy_engine.normalization import normalize_offers
from services.security_kernel.merchant_registry import UNKNOWN_TRUST, MerchantRegistry
from sqlalchemy import select
from tests.conftest import collect_quotes, make_constraints


def _spoof_constraints():
    """The adversarial scenario's policy: only merchant_a may trade, evil is
    explicitly blocked."""
    return make_constraints(
        min_rating=4.2,
        allowed_merchants=["merchant_a"],
        blocked_merchants=["evil"],
    )


# --------------------------------------------------------------------------- #
# IDENTITY SPOOF
# --------------------------------------------------------------------------- #
def test_identity_spoof_is_detected_and_offer_rejected():
    # actual merchant = evil; raw merchant_id = merchant_a; trust claim = 1.0
    c = _spoof_constraints()
    norms = normalize_offers(collect_quotes(c, merchants=[SpoofingMerchant()]), c)
    assert len(norms) == 1
    offer = norms[0]

    # Identity resolves to the AUTHENTICATED merchant, not the claim.
    assert offer.merchant_id.value == "evil"
    assert offer.claimed_merchant_id.value == "merchant_a"
    assert offer.identity_mismatch is True

    # The offer is rejected, and the spoof is named explicitly.
    assert offer.valid is False
    assert ReasonCode.MERCHANT_IDENTITY_MISMATCH in offer.rejection_reasons


def test_spoofed_merchant_cannot_bypass_allow_or_block_policy():
    c = _spoof_constraints()
    offer = normalize_offers(collect_quotes(c, merchants=[SpoofingMerchant()]), c)[0]
    reasons = set(offer.rejection_reasons)
    # Claiming to be merchant_a did NOT satisfy the allow-list...
    assert ReasonCode.MERCHANT_NOT_ALLOWED in reasons
    # ...and did not evade the block-list either.
    assert ReasonCode.BLOCKED_MERCHANT in reasons
    assert ReasonCode.MERCHANT_IDENTITY_MISMATCH in reasons
    assert offer.valid is False


def test_provenance_source_never_uses_the_claimed_identity():
    c = _spoof_constraints()
    offer = normalize_offers(collect_quotes(c, merchants=[SpoofingMerchant()]), c)[0]
    for field in ("claimed_merchant_id", "product_id", "title", "amount_inr", "rating"):
        source = getattr(offer, field).source
        assert source == "merchant:evil"
        assert "merchant_a" not in source


@pytest.mark.asyncio
async def test_spoof_records_security_violation_on_the_runtime_path(session):
    req = CreateMissionRequest(quantity=1, constraints=_spoof_constraints())
    mission = await Orchestrator(merchants=[MockMerchantA(), SpoofingMerchant()]).run(session, req)

    events = await list_events(session, mission.id)
    violations = [e for e in events if e.event_type == EventType.SECURITY_VIOLATION.value]
    spoofs = [
        e
        for e in violations
        if e.payload["reason_code"] == ReasonCode.MERCHANT_IDENTITY_MISMATCH.value
    ]
    assert len(spoofs) == 1
    payload = spoofs[0].payload
    assert payload["authenticated_merchant_id"] == "evil"
    assert payload["claimed_merchant_id"] == "merchant_a"
    assert payload["rejected"] is True

    # The violation is part of the tamper-evident chain.
    assert [e.sequence for e in events] == list(range(len(events)))

    # Persisted offers record the authenticated identity, and the evil offer is
    # invalid and unranked, so it can never be selected.
    offers = (
        (await session.execute(select(Offer).where(Offer.mission_id == mission.id))).scalars().all()
    )
    evil = [o for o in offers if o.merchant_id == "evil"]
    assert len(evil) == 1
    assert evil[0].valid is False
    assert evil[0].rank is None
    assert evil[0].raw["claimed_merchant_id"] == "merchant_a"
    # No offer was persisted under the impersonated identity.
    assert not any(o.merchant_id == "merchant_a" and o.product_id == "evil-eb-99" for o in offers)


# --------------------------------------------------------------------------- #
# TRUST FORGERY
# --------------------------------------------------------------------------- #
def test_merchant_supplied_trust_cannot_modify_server_owned_trust():
    """A payload asserting merchant_trust=1.0 changes nothing: the field does
    not exist on the payload schema, and trust is read from the registry."""
    c = make_constraints()
    offer = normalize_offers(collect_quotes(c, merchants=[SpoofingMerchant()]), c)[0]

    # The forged key never became data.
    assert "merchant_trust" not in RawMerchantOffer.model_fields
    # The server-owned score for an unknown merchant stands.
    assert offer.merchant_trust.value == UNKNOWN_TRUST
    assert offer.merchant_trust.value != 1.0
    assert offer.merchant_trust.source == "merchant-registry:evil"
    assert offer.merchant_trust.authority == AuthorityLevel.SYSTEM_SECURITY_POLICY
    assert offer.merchant_trust.tainted is False


def test_known_merchant_trust_comes_from_registry_not_payload():
    c = make_constraints()
    norms = normalize_offers(collect_quotes(c), c)
    by_merchant = {o.merchant_id.value: o.merchant_trust.value for o in norms}
    assert by_merchant["merchant_a"] == MerchantRegistry().trust_for("merchant_a") == 0.9
    assert by_merchant["merchant_b"] == MerchantRegistry().trust_for("merchant_b") == 0.75


def test_spoofer_claiming_a_high_trust_merchant_still_gets_its_own_score():
    """Impersonating merchant_a (registry trust 0.9) does not lend the spoofer
    merchant_a's reputation — trust is looked up by AUTHENTICATED id."""
    c = make_constraints(min_merchant_trust=0.8)
    offer = normalize_offers(collect_quotes(c, merchants=[SpoofingMerchant()]), c)[0]
    assert MerchantRegistry().trust_for("merchant_a") == 0.9
    assert offer.merchant_trust.value == UNKNOWN_TRUST
    assert ReasonCode.MERCHANT_TRUST_TOO_LOW in offer.rejection_reasons


def test_display_name_comes_from_registry_not_payload():
    c = make_constraints()
    offer = normalize_offers(collect_quotes(c, merchants=[SpoofingMerchant()]), c)[0]
    # The payload said "Aurora Audio"; the registry has no record for `evil`.
    assert offer.merchant_name.value == "evil"
    assert offer.merchant_name.source == "merchant-registry:evil"
    assert offer.merchant_name.tainted is False


# --------------------------------------------------------------------------- #
# TRANSPORT / REGISTRY
# --------------------------------------------------------------------------- #
def test_transport_identity_comes_from_registration_not_payload():
    context = MerchantTransport().connect(SpoofingMerchant())
    assert context.identity.merchant_id == "evil"
    assert context.identity.auth_method == MerchantAuthMethod.IN_PROCESS_ADAPTER
    assert context.record.known is False
    assert context.trust_score == UNKNOWN_TRUST


def test_transport_preserves_identity_per_merchant():
    c = make_constraints()
    quotes = MerchantTransport().collect(
        [MockMerchantA(), MockMerchantB(), SpoofingMerchant()], c, 1
    )
    assert [q.context.merchant_id for q in quotes] == ["merchant_a", "merchant_b", "evil"]
    # Responses are not flattened: each quote still knows who produced it.
    assert all(len(q.offers) > 0 for q in quotes)


def test_identity_is_immutable_once_authenticated():
    identity = MerchantIdentity(
        merchant_id="merchant_a",
        auth_method=MerchantAuthMethod.IN_PROCESS_ADAPTER,
        channel="in-process",
    )
    with pytest.raises(ValidationError):
        identity.merchant_id = "evil"  # type: ignore[misc]


def test_registry_is_the_only_trust_source_and_defaults_to_zero():
    registry = MerchantRegistry()
    assert registry.is_known("merchant_a") is True
    assert registry.is_known("evil") is False
    assert registry.trust_for("evil") == UNKNOWN_TRUST
    record = registry.record_for("evil")
    assert record.known is False
    assert record.trust_score == 0.0


def test_registry_trust_is_reflected_in_the_offer_trust_label():
    c = make_constraints()
    offer = normalize_offers(collect_quotes(c, merchants=[MockMerchantA()]), c)[0]
    assert offer.merchant_trust.trust == TrustLevel.TRUSTED
    assert offer.merchant_trust.tainted is False
