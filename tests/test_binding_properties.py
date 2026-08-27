"""Property/invariant tests for transaction binding.

The contract under test:

    For every valid authorization A bound to transaction T,
    changing ANY bound field of T must make validation fail.

Two complementary strategies:

* An **exhaustive** pass over ``BOUND_FIELDS`` using the declared mutator table,
  with a completeness guard so a new bound field cannot be added without a
  proof that it is protected.
* A **randomized** pass with Hypothesis, which explores value combinations no
  hand-written table would think to try (empty-ish strings, extreme quantities,
  timestamps at boundaries, adversarially similar field values).
"""

from datetime import datetime, timedelta, timezone

from hypothesis import given, settings
from hypothesis import strategies as st
from packages.schemas.transaction import BOUND_FIELDS, BoundTransaction
from services.security_kernel.binding import digests_match
from tests.conftest import FIELD_MUTATIONS, approved_transaction, mutations_for


# --------------------------------------------------------------------------- #
# Exhaustive: the mutator table must cover every bound field
# --------------------------------------------------------------------------- #
def test_every_bound_field_has_a_mutator():
    """Completeness guard for the property below.

    Without this, adding a bound field and forgetting to declare a mutation
    would leave that field's protection unproven while the suite stayed green.
    """
    assert set(FIELD_MUTATIONS) == set(BOUND_FIELDS)


def test_property_every_single_field_mutation_invalidates_the_binding():
    """The stated Phase 3 property, proven exhaustively over all bound fields."""
    approved = approved_transaction()
    digest = approved.digest()
    checked = 0
    for field in BOUND_FIELDS:
        for mutated in mutations_for(approved, field):
            assert digests_match(digest, mutated) is False, (
                f"mutating bound field '{field}' left the binding valid"
            )
            checked += 1
    # Every field contributed at least one proven mutation.
    assert checked >= len(BOUND_FIELDS)


# --------------------------------------------------------------------------- #
# Randomized: Hypothesis
# --------------------------------------------------------------------------- #
#: Printable, non-empty identifiers within the schema's length bounds.
_identifiers = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=126),
    min_size=1,
    max_size=40,
)
_versions = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=126),
    min_size=1,
    max_size=32,
)
_currencies = st.sampled_from(["INR", "USD", "EUR", "GBP", "JPY"])
_nonces = st.text(alphabet="0123456789abcdef", min_size=64, max_size=64)
_expiries = st.datetimes(
    min_value=datetime(2027, 1, 1),
    max_value=datetime(2035, 1, 1),
).map(lambda d: d.replace(tzinfo=timezone.utc))


@st.composite
def bound_transactions(draw) -> BoundTransaction:
    return BoundTransaction(
        merchant_id=draw(_identifiers),
        product_id=draw(_identifiers),
        quantity=draw(st.integers(min_value=1, max_value=100)),
        amount_inr=draw(st.integers(min_value=1, max_value=10_000_000)),
        currency=draw(_currencies),
        policy_version=draw(_versions),
        offer_version=draw(_versions),
        expires_at=draw(_expiries),
        nonce=draw(_nonces),
    )


@settings(max_examples=200, deadline=None)
@given(bound_transactions())
def test_property_digest_is_stable_across_serialization(txn):
    """A transaction that survives a round trip must hash identically —
    otherwise a benign persistence step could break a valid authorization."""
    assert BoundTransaction.model_validate(txn.model_dump()).digest() == txn.digest()


@settings(max_examples=200, deadline=None)
@given(bound_transactions())
def test_property_exact_transaction_always_validates(txn):
    assert digests_match(txn.digest(), txn) is True


@settings(max_examples=300, deadline=None)
@given(bound_transactions(), st.sampled_from(BOUND_FIELDS), st.data())
def test_property_random_single_field_change_invalidates(txn, field, data):
    """For an arbitrary valid transaction, changing any one bound field to any
    other legal value must break the binding."""
    replacement = data.draw(
        {
            "merchant_id": _identifiers,
            "product_id": _identifiers,
            "quantity": st.integers(min_value=1, max_value=100),
            "amount_inr": st.integers(min_value=1, max_value=10_000_000),
            "currency": _currencies,
            "policy_version": _versions,
            "offer_version": _versions,
            "expires_at": _expiries,
            "nonce": _nonces,
        }[field]
    )
    mutated = txn.model_copy(update={field: replacement})
    if getattr(mutated, field) == getattr(txn, field):
        # Hypothesis drew the same value; there is no mutation to detect.
        assert digests_match(txn.digest(), mutated) is True
        return
    assert digests_match(txn.digest(), mutated) is False


@settings(max_examples=200, deadline=None)
@given(bound_transactions(), bound_transactions())
def test_property_distinct_transactions_have_distinct_digests(left, right):
    """No two transactions differing in any bound field may share a digest.

    This is the collision property a naive concatenated digest fails: it is what
    stops an attacker from substituting one approved transaction for another.
    """
    if left.canonical_fields() == right.canonical_fields():
        assert left.digest() == right.digest()
    else:
        assert left.digest() != right.digest()


@settings(max_examples=100, deadline=None)
@given(
    st.text(alphabet=st.characters(min_codepoint=33, max_codepoint=126), min_size=1, max_size=20),
    st.text(alphabet=st.characters(min_codepoint=33, max_codepoint=126), min_size=1, max_size=20),
)
def test_property_no_field_boundary_collisions(left, right):
    """Splitting the same concatenated text across two fields at a different
    point must produce a different digest. A naive `a + b` digest fails this for
    every input; the canonical encoding must pass for all of them."""
    joined = left + right
    for split in range(1, len(joined)):
        a, b = joined[:split], joined[split:]
        if (a, b) == (left, right):
            continue
        assert (
            approved_transaction(merchant_id=a, product_id=b).digest()
            != approved_transaction(merchant_id=left, product_id=right).digest()
        )


@settings(max_examples=100, deadline=None)
@given(st.integers(min_value=1, max_value=3600))
def test_property_expiry_shift_always_changes_the_digest(seconds):
    """Extending an authorization's window is itself a mutation: an attacker
    cannot buy extra replay time without invalidating the binding."""
    base = approved_transaction()
    extended = base.model_copy(update={"expires_at": base.expires_at + timedelta(seconds=seconds)})
    assert digests_match(base.digest(), extended) is False
