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
    adapters,
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
    adapters,
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

#: THE PHASE 6 CANONICAL BENCHMARK, PINNED BY ID.
#:
#: 47 scenarios: 36 malicious, 10 benign controls, 1 demonstrated known
#: limitation. This is the set the published Phase 6 baseline was measured over
#: — 470 runs at 10 iterations, 360/360 malicious blocked, 100/100 controls
#: allowed — and it must keep meaning exactly that.
#:
#: Pinned by ID rather than by CATEGORY, deliberately. Phase 8 added three
#: benign adapter controls, and every one of them lands in BENIGN_CONTROL: a
#: category filter would have quietly moved the control denominator from 100 to
#: 130 and reported the result as though it were the same benchmark. A
#: denominator that grows on its own makes two runs incomparable while both look
#: fine, so the canonical set is a list somebody has to edit on purpose.
#:
#: New work belongs in an EXPANDED run (``--all``), reported separately and
#: never merged into these totals.
PHASE6_CANONICAL_SCENARIOS: tuple[str, ...] = (
    # INPUT_TRUST (4)
    "merchant_prompt_injection",
    "merchant_identity_spoof",
    "merchant_trust_forgery",
    "malformed_agent_output",
    # AUTHORITY (3)
    "authority_escalation",
    "policy_mutation",
    "capability_escalation",
    # TRANSACTION (6)
    "hard_budget_bypass",
    "transaction_mutation",
    "authorization_replay",
    "stale_authorization",
    "policy_version_mutation",
    "offer_version_mutation",
    # PAYMENT_RELIABILITY (7)
    "idempotency_conflict",
    "duplicate_payment",
    "provider_timeout_after_create",
    "provider_amount_mismatch",
    "provider_currency_mismatch",
    "provider_idempotency_key_mismatch",
    "wrong_provider_adapter",
    # WEBHOOK (3)
    "webhook_forgery",
    "webhook_replay",
    "webhook_out_of_order",
    # AUDIT (7)
    "audit_payload_tamper",
    "audit_hash_tamper",
    "audit_chain_tamper",
    "audit_actor_tamper",
    "audit_recomputed_hash_tamper",
    "audit_middle_event_deleted",
    "audit_event_injection",
    # KNOWN_LIMITATION (1)
    "audit_tail_truncation",
    # CONCURRENCY (6) — PostgreSQL
    "pg_concurrent_authorization_consumption",
    "pg_concurrent_same_key_payment",
    "pg_conflicting_idempotency_key",
    "pg_outbox_double_claim",
    "pg_concurrent_terminal_webhook_race",
    "pg_concurrent_audit_append",
    # BENIGN_CONTROL (10)
    "control_allowed_transaction",
    "control_require_approval_transaction",
    "control_valid_authorization_consumption",
    "control_legitimate_payment",
    "control_legitimate_retry",
    "control_transient_retry_recovers",
    "control_valid_webhook",
    "control_valid_reconciliation",
    "control_audit_chain_verifies",
    "control_trusted_replay",
)

#: The thirteen Phase 8 adapter-boundary scenarios, mapped the same way and for
#: the same reason: a renamed or dropped adapter attack must fail a test rather
#: than quietly shrink the claim. Kept SEPARATE from ``REQUIRED_SCENARIOS`` so
#: the Phase 6 required set stays exactly the fifteen it has always been.
REQUIRED_ADAPTER_SCENARIOS: dict[str, str] = {
    "1. ADAPTER IDENTITY SPOOF": "adapter_identity_spoof",
    "2. PROTOCOL VERSION SPOOF": "adapter_protocol_version_spoof",
    "3. CALLER CAPABILITY INJECTION": "adapter_capability_injection",
    "4. MERCHANT TRUST INJECTION": "adapter_merchant_trust_injection",
    "5. POLICY OVERRIDE SMUGGLING": "adapter_policy_override_smuggling",
    "6. AUTHORIZATION ARTIFACT FORGERY": "adapter_authorization_forgery",
    "7. PAYMENT.EXECUTE TOOL-CALL ESCALATION": "adapter_payment_execute_escalation",
    "8. TRANSACTION MUTATION DURING TRANSLATION": "adapter_transaction_mutation",
    "9. CONFUSED DEPUTY": "adapter_confused_deputy",
    "10. MALFORMED PROTOCOL PAYLOAD": "adapter_malformed_payload",
    "11. UNKNOWN PRIVILEGED FIELD INJECTION": "adapter_unknown_privileged_field",
    "12. CROSS-FAMILY ADAPTER CONFUSION": "adapter_cross_family_confusion",
    "13. ADAPTER REGISTRY BYPASS": "adapter_registry_bypass",
}

__all__ = [
    "ALL_SCENARIOS",
    "PHASE6_CANONICAL_SCENARIOS",
    "REGISTRY",
    "REQUIRED_ADAPTER_SCENARIOS",
    "REQUIRED_SCENARIOS",
]
