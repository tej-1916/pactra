"""Capability firewall invariant (C)."""

import pytest
from packages.schemas.capability import Capability, buyer_agent_capabilities
from services.security_kernel.capability import (
    CapabilityDenied,
    enforce,
    permits,
    run_privileged,
)


def test_buyer_agent_can_propose_but_not_execute():
    caps = buyer_agent_capabilities()
    assert permits(caps, Capability.PAYMENT_PROPOSE) is True
    assert permits(caps, Capability.PAYMENT_EXECUTE) is False


# Invariant C: a buyer agent denied payment.execute cannot reach privileged
# execution — the operation never runs.
def test_denied_capability_makes_executor_unreachable():
    caps = buyer_agent_capabilities()
    executed = {"ran": False}

    def privileged_execute() -> str:
        executed["ran"] = True
        return "PAID"

    with pytest.raises(CapabilityDenied) as exc:
        run_privileged(caps, Capability.PAYMENT_EXECUTE, privileged_execute)

    assert exc.value.reason_code == "CAPABILITY_DENIED"
    assert executed["ran"] is False  # executor was never reached


def test_allowed_capability_runs_operation():
    caps = buyer_agent_capabilities()
    result = run_privileged(caps, Capability.PAYMENT_PROPOSE, lambda: "PROPOSED")
    assert result == "PROPOSED"


def test_default_deny_for_unlisted_capability():
    caps = buyer_agent_capabilities()
    # merchant.modify is explicitly denied; enforce must raise.
    with pytest.raises(CapabilityDenied):
        enforce(caps, Capability.MERCHANT_MODIFY)
