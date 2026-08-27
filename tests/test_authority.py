"""Authority lattice invariants (A and D)."""

import pytest
from packages.schemas.provenance import (
    AuthorityLevel,
    agent_value,
    authoritative,
    untrusted,
)
from services.security_kernel.authority import (
    AuthorityEscalation,
    assert_can_write,
    can_write,
    guard_write,
    merge_keep_higher,
)


# Invariant A: merchant-controlled budget cannot overwrite user policy.
def test_merchant_budget_cannot_overwrite_user_policy():
    merchant_budget = untrusted(100000, source="merchant:merchant_b")
    with pytest.raises(AuthorityEscalation) as exc:
        assert_can_write("hard_limit", merchant_budget, AuthorityLevel.USER_POLICY)
    assert exc.value.reason_code == "AUTHORITY_ESCALATION"
    assert exc.value.source == AuthorityLevel.MERCHANT_DATA
    assert exc.value.target == AuthorityLevel.USER_POLICY
    assert exc.value.field == "hard_limit"


# Invariant D: higher-authority user policy remains authoritative against
# lower-authority agent/merchant input.
def test_user_policy_remains_authoritative_against_agent():
    user_limit = authoritative(4500, source="user-policy")
    agent_attempt = agent_value(99999, source="buyer-agent")
    with pytest.raises(AuthorityEscalation):
        merge_keep_higher("hard_limit", user_limit, agent_attempt)
    # The protected value is unchanged.
    assert user_limit.value == 4500


def test_equal_or_higher_authority_may_write():
    assert can_write(AuthorityLevel.USER_POLICY, AuthorityLevel.USER_POLICY)
    assert can_write(AuthorityLevel.USER_POLICY, AuthorityLevel.SYSTEM_SECURITY_POLICY)
    # A same-or-higher authority update is allowed and wins.
    current = authoritative(4500)
    higher = authoritative(4000, source="user-policy-v2")
    assert merge_keep_higher("hard_limit", current, higher).value == 4000


def test_guard_write_denies_lower_authority():
    with pytest.raises(AuthorityEscalation):
        guard_write(
            AuthorityLevel.MERCHANT_DATA,
            AuthorityLevel.AUTHORIZATION,
            field="authorization",
        )
