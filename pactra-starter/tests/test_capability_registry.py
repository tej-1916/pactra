"""#5 capability forgery + #6 default-deny."""

import pytest
from packages.schemas.capability import Capability, CapabilitySet
from packages.schemas.domain import CreateMissionRequest
from pydantic import ValidationError
from services.security_kernel.capability import CapabilityDenied, permits, run_privileged
from services.security_kernel.capability_registry import capabilities_for


# #5: an agent cannot manufacture its own capability set to grant privileges.
def test_registry_is_source_of_truth_not_request():
    trusted = capabilities_for("buyer-agent")
    assert Capability.PAYMENT_EXECUTE not in trusted.allow
    assert Capability.PAYMENT_EXECUTE in trusted.deny

    # Even if an attacker builds a CapabilitySet granting payment.execute, the
    # trusted registry — the only sanctioned source — never returns it.
    forged = CapabilitySet(principal="buyer-agent", allow={Capability.PAYMENT_EXECUTE})
    assert permits(forged, Capability.PAYMENT_EXECUTE) is True  # the forgery itself
    resolved = capabilities_for("buyer-agent")
    assert permits(resolved, Capability.PAYMENT_EXECUTE) is False  # ignored


def test_request_schema_rejects_client_supplied_capabilities():
    # The mission request cannot carry capabilities/authority (extra="forbid").
    with pytest.raises(ValidationError):
        CreateMissionRequest.model_validate(
            {
                "constraints": {
                    "category": "x",
                    "soft_budget_inr": 100,
                    "hard_limit_inr": 100,
                },
                "capabilities": {"allow": ["payment.execute"]},
            }
        )


def test_unknown_principal_defaults_to_deny_everything():
    caps = capabilities_for("unknown-agent")
    assert caps.allow == set()
    with pytest.raises(CapabilityDenied):
        run_privileged(caps, Capability.PAYMENT_PROPOSE, lambda: "nope")


# #6: a capability in neither allow nor deny is denied by default.
def test_default_deny_for_capability_in_neither_set():
    caps = CapabilitySet(principal="p", allow=set(), deny=set())
    assert permits(caps, Capability.CATALOG_READ) is False
    ran = {"x": False}

    def op():
        ran["x"] = True

    with pytest.raises(CapabilityDenied):
        run_privileged(caps, Capability.CATALOG_READ, op)
    assert ran["x"] is False
