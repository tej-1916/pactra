"""The scenarios themselves, run against real PACTRA.

Two kinds of test live here.

**Regression.** Phase 4's duplicate prevention and Phase 5's tamper evidence are
re-proved through the Attack Lab, so a future change that weakened either would
fail here as well as in its own suite. The Attack Lab is an independent
observer: it measures counts and reason codes rather than calling the same
assertions the original tests do.

**Harness self-tests.** A scenario that cannot fail proves nothing, so the
critical duplicate-payment scenario is run against a deliberately broken
provider and asserted to report NOT_BLOCKED. That is the only way to know the
BLOCKED it reports for real PACTRA is a measurement rather than a foregone
conclusion.
"""

from __future__ import annotations

from typing import Any

import pytest
from services.attack_lab.models import AttackStatus
from services.attack_lab.registry import load_registry
from services.attack_lab.runner import run_once
from services.attack_lab.scenarios import payment_reliability as pr
from services.attack_lab.scenarios.adversaries import NonIdempotentProvider
from services.payment_executor.providers.fake import FaultMode

pytestmark = pytest.mark.attack_lab


async def _run(scenario_id: str):
    scenario = load_registry().get(scenario_id)
    return (await run_once([scenario], include_postgres=False))[0]


# --------------------------------------------------------------------------- #
# Phase 5 regression: tamper evidence, observed from outside
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("scenario_id", "expected_reason"),
    [
        ("audit_payload_tamper", "AUDIT_EVENT_HASH_MISMATCH"),
        ("audit_hash_tamper", "AUDIT_EVENT_HASH_MISMATCH"),
        ("audit_chain_tamper", "AUDIT_PREVIOUS_HASH_MISMATCH"),
        ("audit_actor_tamper", "AUDIT_EVENT_HASH_MISMATCH"),
        ("audit_recomputed_hash_tamper", "AUDIT_PREVIOUS_HASH_MISMATCH"),
        ("audit_middle_event_deleted", "AUDIT_SEQUENCE_GAP"),
    ],
)
async def test_phase5_audit_verification_still_catches_tampering(scenario_id, expected_reason):
    result = await _run(scenario_id)

    assert result.status is AttackStatus.BLOCKED, result.error
    assert result.reason_code == expected_reason
    effects = result.observed_effects
    # The tamper actually landed — a no-op edit leaving an intact chain would
    # otherwise look exactly like a working verifier.
    assert effects["rows_changed_by_tamper"] >= 1
    assert effects["chain_valid_before_attack"] is True
    assert effects["tamper_detected"] is True
    # And a tampered chain yields no projection at all, not one with a warning.
    assert effects["replay_trusted"] is False
    assert effects["replay_state_withheld"] is True
    # The verifier repaired nothing.
    assert effects["verifier_left_the_row_as_the_attacker_left_it"] is True


async def test_audit_event_injection_is_refused_at_both_layers():
    """Two controls answer, and they are measured separately.

    A duplicated sequence never lands — UNIQUE(mission_id, sequence) refuses it
    below the verifier. The same forged row appended past the end DOES land, and
    the verifier catches it. Crediting the verifier with the first refusal would
    attribute a database guarantee to application logic.
    """
    result = await _run("audit_event_injection")

    assert result.status is AttackStatus.BLOCKED, result.error
    effects = result.observed_effects
    assert effects["duplicate_sequence_insert_refused_by_storage"] is True
    assert effects["events_after_duplicate_attempt"] == effects["events_before_attack"]
    assert effects["chain_valid_after_duplicate_attempt"] is True
    assert effects["verifier_detected_injection"] is True
    assert result.reason_code == "AUDIT_SEQUENCE_GAP"
    assert effects["replay_trusted"] is False


async def test_tail_truncation_is_reported_as_a_limitation_not_a_blocked_attack():
    """The one thing the chain cannot detect, measured rather than asserted."""
    result = await _run("audit_tail_truncation")

    assert result.status is AttackStatus.NOT_BLOCKED
    # Expected, so it does not count as a failure — and its category keeps it
    # out of the attack block rate entirely.
    assert result.outcome_as_expected
    assert not result.is_malicious
    effects = result.observed_effects
    assert effects["events_deleted"] >= 1
    assert effects["chain_still_verifies"] is True
    assert effects["counted_as_a_blocked_attack"] is False


# --------------------------------------------------------------------------- #
# Phase 4 regression: duplicate prevention, observed from outside
# --------------------------------------------------------------------------- #
async def test_phase4_payment_recovery_still_prevents_duplicates():
    """The lost-response case: one create call, one payment, original adopted."""
    result = await _run("provider_timeout_after_create")

    assert result.status is AttackStatus.BLOCKED, result.error
    effects = result.observed_effects
    # The required conditions, each measured.
    assert effects["logical_payments"] == 1
    assert effects["provider_payments"] == 1
    assert effects["provider_payments_ever_created"] == 1
    assert effects["duplicate_effect"] is False
    assert effects["recovered_original_payment"] is True
    # Uncertainty was entered rather than guessed past, and nothing was linked
    # while PACTRA had no evidence of a payment.
    assert effects["entered_uncertain_state"] is True
    assert effects["linked_a_payment_while_uncertain"] is False
    # Against a provider with NO idempotency guarantee of its own.
    assert effects["provider_is_idempotent"] is False
    assert effects["provider_create_calls"] == 1


async def test_phase4_repeated_same_key_requests_create_one_payment():
    result = await _run("duplicate_payment")

    assert result.status is AttackStatus.BLOCKED, result.error
    effects = result.observed_effects
    assert effects["requests_issued"] == 5
    assert effects["requests_that_created"] == 1
    assert effects["logical_payments"] == 1
    assert effects["provider_payments"] == 1
    # Every repeat was ACCEPTED: refusing a well-formed retry would be a
    # different bug wearing this test's passing grade.
    assert effects["requests_accepted"] == effects["requests_issued"]


async def test_phase3_replay_produces_no_second_payment():
    result = await _run("authorization_replay")

    assert result.status is AttackStatus.BLOCKED, result.error
    effects = result.observed_effects
    assert effects["payment_intents_before"] == effects["payment_intents_after"] == 1
    assert effects["unauthorized_effect"] is False
    assert effects["authorization_status_after"] == "CONSUMED"
    assert result.reason_code == "AUTHORIZATION_REPLAY_DETECTED"


async def test_every_bound_field_mutation_is_refused():
    result = await _run("transaction_mutation")

    assert result.status is AttackStatus.BLOCKED, result.error
    effects = result.observed_effects
    # Exhaustive by construction: a bound field with no mutator fails here
    # rather than silently shrinking what the scenario proves.
    assert effects["bound_fields_without_a_mutator"] == []
    assert effects["mutations_attempted"] == effects["mutations_refused"]
    assert effects["refused_with_binding_failure"] == effects["mutations_attempted"]
    assert effects["fields_that_went_through"] == []
    assert effects["authorization_unspent"] is True


# --------------------------------------------------------------------------- #
# Harness self-test: the critical scenario CAN fail
# --------------------------------------------------------------------------- #
class _LyingProvider(NonIdempotentProvider):
    """Falsely declares idempotent create, then denies holding a payment.

    This mutation corrupts both inputs to the retry decision: the adapter claims
    repeated creates are safe and its lookup denies the existing payment. That
    must make the attack scenario detect a duplicate; otherwise its BLOCKED
    result for the real, correctly fenced adapter would be unfalsifiable.
    """

    create_retries_are_idempotent = True

    async def get_payment(self, *, provider_payment_id=None, idempotency_key=None):
        self.get_calls.append((provider_payment_id, idempotency_key))
        return None


async def test_the_timeout_scenario_detects_a_real_duplicate():
    """A check that cannot fail is not a check.

    This is the mutation test for the harness itself. With an adapter that lies
    about both create idempotency and what it holds, a second payment genuinely
    IS created and the scenario must report NOT_BLOCKED. Without this, the
    BLOCKED result for real PACTRA would be unfalsifiable.
    """

    async def lying_setup(context: Any) -> dict[str, Any]:
        provider = _LyingProvider()
        provider.queue_faults(FaultMode.TIMEOUT_AFTER_CREATE, FaultMode.SUCCESS)
        context.provider = provider
        mission_id, authorization_id, _ = await context.authorized_mission()
        key = "attack-lost-response"
        request = await pr._request_payment(
            context,
            mission_id=mission_id,
            authorization_id=authorization_id,
            idempotency_key=key,
        )
        return {
            "mission_id": mission_id,
            "key": key,
            "request": request,
            "census": await context.census(),
        }

    mutated = pr.PROVIDER_TIMEOUT_AFTER_CREATE.model_copy(update={"setup": lying_setup})
    result = (await run_once([mutated], include_postgres=False))[0]

    assert result.status is AttackStatus.NOT_BLOCKED, (
        "the timeout scenario failed to notice a duplicate provider payment; "
        "its BLOCKED result for real PACTRA would therefore mean nothing"
    )
    effects = result.observed_effects
    assert effects["provider_payments_ever_created"] == 2
    assert effects["duplicate_effect"] is True
    assert effects["recovered_original_payment"] is False


async def test_the_prompt_injection_scenario_detects_a_changed_outcome():
    """Second mutation test: differential comparison must be able to disagree."""
    from services.attack_lab.scenarios import input_trust
    from services.attack_lab.scenarios.adversaries import OverpricedMerchant

    async def divergent_setup(context: Any) -> dict[str, Any]:
        # A baseline whose offer differs materially from the injected merchant's.
        # The comparison MUST notice, or it is not comparing anything.
        from services.attack_lab.scenarios._helpers import mission_snapshot, run_mission

        baseline_id = await run_mission(context, merchants=[OverpricedMerchant(price=4400)])
        return {
            "baseline_id": baseline_id,
            "baseline": await mission_snapshot(context, baseline_id),
            "census": await context.census(),
        }

    mutated = input_trust.MERCHANT_PROMPT_INJECTION.model_copy(update={"setup": divergent_setup})
    result = (await run_once([mutated], include_postgres=False))[0]

    assert result.status is AttackStatus.NOT_BLOCKED
    assert result.observed_effects["outcome_identical_to_clean_twin"] is False


# --------------------------------------------------------------------------- #
# The whole SQLite suite, once
# --------------------------------------------------------------------------- #
async def test_every_sqlite_scenario_reaches_its_expected_outcome():
    """The end-to-end statement: nothing errors, nothing is inconclusive, nothing bypasses."""
    from services.attack_lab.evaluation import evaluate
    from services.attack_lab.models import Backend

    report = await evaluate(iterations=1, include_postgres=False)
    sqlite_runs = [r for r in report.results if r.backend is Backend.SQLITE]

    unexpected = [
        (r.scenario_id, r.status.value, r.expected_status.value, r.error)
        for r in sqlite_runs
        if not r.outcome_as_expected
    ]
    assert not unexpected, f"scenarios did not reach their expected outcome: {unexpected}"

    errors = [(r.scenario_id, r.error) for r in sqlite_runs if r.status is AttackStatus.ERROR]
    assert not errors, f"scenarios errored: {errors}"

    inconclusive = [r.scenario_id for r in sqlite_runs if r.status is AttackStatus.INCONCLUSIVE]
    assert not inconclusive, f"scenarios were inconclusive: {inconclusive}"

    assert report.metrics.attacks_not_blocked == 0
    assert report.metrics.controls_blocked == 0
    assert report.findings == []
