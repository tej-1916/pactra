"""Transaction binding: the digest, and what it commits to.

These tests exercise the binding primitive directly. The mutation-detection
contract (#1-#8 of the Phase 3 test list) is proven here against the digest and
again in tests/test_replay_protection.py against the live consumption path.
"""

from datetime import datetime, timedelta, timezone

import pytest
from packages.schemas.canonical import canonical_bytes, canonical_digest
from packages.schemas.domain import PolicyDecision, PolicyOutcome, ReasonCode
from packages.schemas.invariants import InvariantViolation
from packages.schemas.transaction import (
    BINDING_VERSION,
    BOUND_FIELDS,
    BoundTransaction,
    compute_offer_version,
)
from pydantic import ValidationError
from services.security_kernel.binding import build_bound_transaction, digests_match
from tests.conftest import approved_transaction, mutations_for


# --------------------------------------------------------------------------- #
# The digest covers exactly the declared bound fields
# --------------------------------------------------------------------------- #
def test_bound_fields_cover_every_model_field():
    """Completeness guard.

    If someone adds a security-sensitive field to BoundTransaction and forgets
    to add it to BOUND_FIELDS, the digest would silently stop covering it and
    that field could be mutated after approval undetected. This test fails first.
    """
    assert set(BOUND_FIELDS) == set(BoundTransaction.model_fields)


def test_digest_covers_every_bound_field():
    txn = approved_transaction()
    covered = txn.canonical_fields()
    assert set(covered) == set(BOUND_FIELDS)


def test_digest_is_deterministic():
    txn = approved_transaction()
    twin = txn.model_copy()
    assert txn.digest() == twin.digest()
    assert txn.digest() == BoundTransaction.model_validate(txn.model_dump()).digest()


def test_digest_is_sha256_hex():
    digest = approved_transaction().digest()
    assert len(digest) == 64
    assert set(digest) <= set("0123456789abcdef")


# --------------------------------------------------------------------------- #
# #1 The exact approved transaction validates
# --------------------------------------------------------------------------- #
def test_exact_approved_transaction_validates():
    txn = approved_transaction()
    assert digests_match(txn.digest(), txn) is True


# --------------------------------------------------------------------------- #
# #2-#8 Mutating any bound field invalidates the binding
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("field", sorted(BOUND_FIELDS))
def test_any_bound_field_mutation_breaks_the_digest(field):
    approved = approved_transaction()
    for mutated in mutations_for(approved, field):
        assert mutated.digest() != approved.digest(), f"mutating '{field}' did not change digest"
        assert digests_match(approved.digest(), mutated) is False


def test_spec_scenario_price_mutation_after_approval():
    """The exact scenario from the Phase 3 brief.

    approved: merchant=A product=P1 amount=3799 quantity=1 currency=INR
    later:    amount=4399
    result:   binding no longer holds
    """
    approved = approved_transaction(
        merchant_id="merchant_a", product_id="P1", amount_inr=3799, quantity=1, currency="INR"
    )
    mutated = approved.model_copy(update={"amount_inr": 4399})
    assert digests_match(approved.digest(), approved) is True
    assert digests_match(approved.digest(), mutated) is False


# --------------------------------------------------------------------------- #
# The digest is not naive concatenation
# --------------------------------------------------------------------------- #
def test_field_boundary_shift_does_not_collide():
    """`merchant_id="ab" + product_id="c"` and `"a" + "bc"` concatenate to the
    same bytes. A naive digest would treat them as one transaction; the
    canonical encoding must not."""
    left = approved_transaction(merchant_id="ab", product_id="c")
    right = approved_transaction(merchant_id="a", product_id="bc")
    assert left.digest() != right.digest()


def test_type_confusion_does_not_collide():
    """Integer 3799, string "3799" and boolean True must all hash differently."""
    domain = "test-domain"
    digests = {
        canonical_digest(domain, {"x": 3799}),
        canonical_digest(domain, {"x": "3799"}),
        canonical_digest(domain, {"x": 1}),
        canonical_digest(domain, {"x": True}),
        canonical_digest(domain, {"x": None}),
    }
    assert len(digests) == 5


def test_key_rename_changes_digest():
    """Field names are part of the preimage: moving a value to a different field
    must not preserve the digest."""
    domain = "test-domain"
    assert canonical_digest(domain, {"amount_inr": 3799}) != canonical_digest(
        domain, {"quantity": 3799}
    )


def test_canonical_encoding_is_order_independent():
    a = canonical_bytes({"b": 2, "a": 1})
    b = canonical_bytes({"a": 1, "b": 2})
    assert a == b


def test_domain_separation_isolates_digests():
    fields = {"x": 1}
    assert canonical_digest("domain-a", fields) != canonical_digest("domain-b", fields)


def test_canonical_encoder_rejects_floats():
    """Binary floats have no reproducible canonical form; hashing them would
    make the digest platform-dependent."""
    with pytest.raises(InvariantViolation):
        canonical_digest("d", {"rating": 4.6})  # type: ignore[dict-item]


def test_canonical_encoder_rejects_naive_datetime():
    with pytest.raises(InvariantViolation):
        canonical_digest("d", {"t": datetime(2026, 1, 1, 12, 0, 0)})


def test_canonical_encoder_rejects_unknown_types():
    with pytest.raises(InvariantViolation):
        canonical_digest("d", {"x": ["a", "b"]})  # type: ignore[dict-item]


def test_equivalent_instants_in_different_zones_hash_alike():
    """The digest commits to an instant, not to a textual timezone offset."""
    utc = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    plus_two = utc.astimezone(timezone(timedelta(hours=2)))
    assert canonical_digest("d", {"t": utc}) == canonical_digest("d", {"t": plus_two})


# --------------------------------------------------------------------------- #
# #13 Malformed input cannot produce a valid bound transaction
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "override",
    [
        {"merchant_id": ""},
        {"product_id": ""},
        {"quantity": 0},
        {"quantity": -1},
        {"amount_inr": 0},
        {"amount_inr": -100},
        {"currency": "RUPEE"},
        {"currency": "IN"},
        {"policy_version": ""},
        {"offer_version": ""},
        {"nonce": "not-hex-!!"},
        {"nonce": "abc"},
        {"nonce": "A" * 64},  # uppercase hex is not the canonical nonce form
    ],
)
def test_malformed_transaction_rejected(override):
    with pytest.raises(ValidationError):
        approved_transaction(**override)


def test_naive_expiry_rejected():
    with pytest.raises((ValidationError, InvariantViolation)):
        approved_transaction(expires_at=datetime(2030, 1, 1, 0, 0, 0))


def test_extra_fields_rejected():
    """A caller cannot smuggle an unbound field into a bound transaction."""
    with pytest.raises(ValidationError):
        BoundTransaction.model_validate(
            {**approved_transaction().model_dump(), "override_limit": 999999}
        )


def test_bound_transaction_is_immutable():
    """A bound transaction cannot be edited in place; a changed transaction is
    necessarily a different object with a different digest."""
    txn = approved_transaction()
    with pytest.raises(ValidationError):
        txn.amount_inr = 4399  # type: ignore[misc]


def test_currency_is_normalized_before_hashing():
    assert (
        approved_transaction(currency="inr").digest()
        == approved_transaction(currency="INR").digest()
    )


# --------------------------------------------------------------------------- #
# Offer content fingerprint
# --------------------------------------------------------------------------- #
def _offer_version(**overrides):
    base = dict(
        merchant_id="merchant_a",
        product_id="P1",
        amount_inr=3799,
        currency="INR",
        rating=4.6,
        in_stock=True,
        offered_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
    )
    base.update(overrides)
    return compute_offer_version(**base)  # type: ignore[arg-type]


def test_offer_version_is_deterministic():
    assert _offer_version() == _offer_version()


@pytest.mark.parametrize(
    "override",
    [
        {"merchant_id": "merchant_b"},
        {"product_id": "P2"},
        {"amount_inr": 4399},
        {"currency": "USD"},
        {"rating": 4.7},
        {"in_stock": False},
        {"offered_at": datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)},
    ],
)
def test_offer_version_changes_with_content(override):
    assert _offer_version(**override) != _offer_version()


# --------------------------------------------------------------------------- #
# The builder binds the right values
# --------------------------------------------------------------------------- #
def _decision(offer, quantity, outcome=PolicyOutcome.REQUIRE_APPROVAL):
    return PolicyDecision(
        decision=outcome,
        policy_version="policy-v1",
        reason_codes=[ReasonCode.SOFT_BUDGET_EXCEEDED],
        requested_amount=offer.amount_inr.value * quantity,
        soft_budget=4000,
        hard_limit=9000,
        selected_offer_id=offer.offer_id,
    )


def test_builder_binds_authenticated_identity_not_the_claim(spoofed_offer):
    """A spoofing merchant must not be able to bind an authorization to the
    identity it is impersonating."""
    offer = spoofed_offer
    offer.valid = True  # force past normalization to isolate the binding rule
    txn = build_bound_transaction(
        offer=offer,
        decision=_decision(offer, 1),
        quantity=1,
        nonce="b" * 64,
        expires_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
    )
    assert offer.claimed_merchant_id.value == "merchant_a"
    assert txn.merchant_id == "evil"  # authenticated identity wins


def test_builder_binds_quantity_multiplied_amount(valid_offer):
    txn = build_bound_transaction(
        offer=valid_offer,
        decision=_decision(valid_offer, 3),
        quantity=3,
        nonce="c" * 64,
        expires_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
    )
    assert txn.quantity == 3
    assert txn.amount_inr == valid_offer.amount_inr.value * 3


def test_builder_refuses_a_denied_decision(valid_offer):
    denied = PolicyDecision(
        decision=PolicyOutcome.DENY,
        policy_version="policy-v1",
        reason_codes=[ReasonCode.HARD_LIMIT_EXCEEDED],
        requested_amount=valid_offer.amount_inr.value,
        soft_budget=100,
        hard_limit=200,
        selected_offer_id=valid_offer.offer_id,
    )
    with pytest.raises(InvariantViolation):
        build_bound_transaction(
            offer=valid_offer,
            decision=denied,
            quantity=1,
            nonce="d" * 64,
            expires_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
        )


def test_builder_refuses_an_invalid_offer(valid_offer):
    valid_offer.valid = False
    with pytest.raises(InvariantViolation):
        build_bound_transaction(
            offer=valid_offer,
            decision=_decision(valid_offer, 1),
            quantity=1,
            nonce="e" * 64,
            expires_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
        )


def test_builder_refuses_an_offer_the_decision_did_not_select(valid_offer, second_offer):
    with pytest.raises(InvariantViolation):
        build_bound_transaction(
            offer=second_offer,
            decision=_decision(valid_offer, 1),
            quantity=1,
            nonce="f" * 64,
            expires_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
        )


def test_binding_version_is_recorded():
    assert BINDING_VERSION == "pactra-txn-bind-v1"
