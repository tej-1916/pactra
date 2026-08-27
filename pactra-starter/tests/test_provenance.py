"""Provenance & taint primitives (supports invariant B)."""

from packages.schemas.provenance import (
    AuthorityLevel,
    TrustLevel,
    agent_value,
    authoritative,
    is_tainted,
    untrusted,
)


def test_authoritative_is_untainted_and_high_authority():
    p = authoritative(4500, source="user-policy")
    assert p.value == 4500
    assert p.trust == TrustLevel.AUTHORITATIVE
    assert p.authority == AuthorityLevel.USER_SIGNED_POLICY
    assert is_tainted(p) is False


def test_merchant_value_is_untrusted_and_tainted():
    p = untrusted(3799, source="merchant:merchant_b")
    assert p.trust == TrustLevel.UNTRUSTED
    assert p.authority == AuthorityLevel.MERCHANT_DATA
    assert is_tainted(p) is True


def test_taint_is_sticky_through_transform():
    p = untrusted(3799.0, source="merchant:x")
    transformed = p.map(lambda v: int(round(v)))
    assert transformed.value == 3799
    assert transformed.transformed is True
    assert transformed.tainted is True  # taint survives transformation
    assert transformed.trust == TrustLevel.UNTRUSTED


def test_authority_ordering():
    assert AuthorityLevel.USER_SIGNED_POLICY > AuthorityLevel.AGENT_PROPOSAL
    assert AuthorityLevel.AGENT_PROPOSAL > AuthorityLevel.MERCHANT_DATA
    assert agent_value(1).authority < authoritative(1).authority
