"""Scenario registration. The single place the attack set is declared.

Registration is an explicit list, not filesystem discovery. The set of attacks
PACTRA claims to run must not depend on which files happen to import cleanly:
a scenario silently vanishing — a renamed module, an import error swallowed
somewhere — would shrink the security claim while the report still said "all
attacks blocked". Here, a missing scenario is a missing name in this list, and
``tests/test_attack_lab_registry.py`` fails if a required one is absent.

Order is registration order, so a batch runs the same way every time.
"""

from __future__ import annotations

from services.attack_lab.models import AttackScenario
from services.attack_lab.registry import REGISTRY, register
from services.attack_lab.scenarios import (
    audit,
    authority,
    concurrency,
    controls,
    input_trust,
    payment_reliability,
    transaction,
    webhook,
)

#: Every scenario module, in benchmark-group order. Malicious groups first so a
#: human-readable run reads as "attacks, then the limitation, then the controls".
_MODULES = (
    input_trust,
    authority,
    transaction,
    payment_reliability,
    webhook,
    audit,
    concurrency,
    controls,
)


def _register_all() -> tuple[AttackScenario, ...]:
    registered: list[AttackScenario] = []
    for module in _MODULES:
        for scenario in module.SCENARIOS:
            # Idempotent under repeated imports: a module imported twice (a test
            # reloading it, a CLI importing the package after a test already
            # did) must not raise DuplicateScenario for a scenario that is
            # already the exact object registered.
            if REGISTRY.has(scenario.id):
                registered.append(REGISTRY.get(scenario.id))
                continue
            registered.append(register(scenario))
    return tuple(registered)


ALL_SCENARIOS = _register_all()

#: The 15 named scenarios the Phase 6 specification requires, mapped to the ids
#: that implement them. Asserted by the test suite, so a rename that dropped one
#: of the required attacks fails rather than quietly reducing coverage.
REQUIRED_SCENARIOS: dict[str, str] = {
    "1. MERCHANT PROMPT INJECTION": "merchant_prompt_injection",
    "2. AUTHORITY ESCALATION": "authority_escalation",
    "3. MERCHANT IDENTITY SPOOF": "merchant_identity_spoof",
    "4. MERCHANT TRUST FORGERY": "merchant_trust_forgery",
    "5. CAPABILITY ESCALATION": "capability_escalation",
    "6. HARD BUDGET / POLICY BYPASS": "hard_budget_bypass",
    "7. TRANSACTION MUTATION AFTER APPROVAL": "transaction_mutation",
    "8. AUTHORIZATION REPLAY": "authorization_replay",
    "9. STALE / EXPIRED AUTHORIZATION": "stale_authorization",
    "10. IDEMPOTENCY CONFLICT": "idempotency_conflict",
    "11. DUPLICATE PAYMENT ATTEMPT": "duplicate_payment",
    "12. PROVIDER TIMEOUT AFTER CREATE": "provider_timeout_after_create",
    "13. FORGED WEBHOOK": "webhook_forgery",
    "14. DUPLICATE / OUT-OF-ORDER WEBHOOK": "webhook_replay",
    "15. AUDIT TAMPERING": "audit_payload_tamper",
}

__all__ = ["ALL_SCENARIOS", "REQUIRED_SCENARIOS", "REGISTRY"]
