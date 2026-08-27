import pytest
from packages.schemas.domain import MissionState as S
from services.agent_orchestrator.state_machine import (
    IllegalTransition,
    assert_transition,
    can_transition,
)


def test_valid_forward_transition():
    assert can_transition(S.CREATED, S.INTENT_PARSED)
    assert can_transition(S.RANKED, S.POLICY_CHECKED)


def test_illegal_transition_raises():
    with pytest.raises(IllegalTransition):
        assert_transition(S.CREATED, S.PAYMENT_SUCCEEDED)


def test_terminal_states_have_no_exits():
    assert not can_transition(S.COMPLETED, S.CREATED)
    assert not can_transition(S.CANCELLED, S.POLICY_CHECKED)
