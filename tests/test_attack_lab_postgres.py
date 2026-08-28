"""PostgreSQL concurrency attacks — where the race guarantees are actually proven.

SQLite serializes writers with a whole-database lock. A race run there is
refused by the database declining to let the interleaving happen, not by the
code under test, so it proves the wrong thing. These tests therefore run the
CONCURRENCY scenarios against a real server and assert on the counts they
measured: exactly one winner out of eight, exactly one payment, exactly one
terminal transition.

They SKIP loudly when no server is reachable. A concurrency guarantee that was
not exercised must never be reported as one that was — which is also why the
scenarios themselves report INCONCLUSIVE rather than BLOCKED in that case, and
why `--require-postgres` exists for CI.
"""

from __future__ import annotations

import pytest
from services.attack_lab.context import PostgresUnavailable, make_postgres_engine
from services.attack_lab.evaluation import evaluate
from services.attack_lab.models import AttackCategory, AttackStatus, Backend
from services.attack_lab.registry import load_registry
from services.attack_lab.runner import run_once

pytestmark = [pytest.mark.postgres, pytest.mark.attack_lab]

#: How many concurrent attempts each race makes. Mirrors the scenarios' own
#: constant rather than restating a number that could drift apart from it.
from services.attack_lab.scenarios.concurrency import RACERS  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
async def _require_postgres():
    """Skip the module — loudly — when no server is reachable."""
    try:
        engine = await make_postgres_engine()
    except PostgresUnavailable as unavailable:
        pytest.skip(
            "PostgreSQL is required for the Phase 6 concurrency attacks. Start it "
            "with `docker compose -f infra/docker-compose.yml up -d`, or point "
            f"PACTRA_TEST_DATABASE_URL at a server. Tried: {unavailable}",
            allow_module_level=True,
        )
    await engine.dispose()


async def _run(scenario_id: str):
    scenario = load_registry().get(scenario_id)
    return (await run_once([scenario], include_postgres=True))[0]


async def test_concurrent_authorization_consumption_has_exactly_one_winner():
    result = await _run("pg_concurrent_authorization_consumption")

    assert result.status is AttackStatus.BLOCKED, result.error
    effects = result.observed_effects
    assert effects["concurrent_attempts"] == RACERS
    assert effects["winners"] == 1, "more than one session consumed one authorization"
    assert effects["losers"] == RACERS - 1
    # On PostgreSQL the loser is refused by the conditional UPDATE, so the exact
    # reason code can be asserted — which is what SQLite could not give.
    assert effects["losses_by_replay_detection"] == RACERS - 1
    assert effects["unauthorized_effect"] is False
    assert effects["final_authorization_status"] == "CONSUMED"


async def test_concurrent_same_key_creates_one_payment():
    result = await _run("pg_concurrent_same_key_payment")

    assert result.status is AttackStatus.BLOCKED, result.error
    effects = result.observed_effects
    assert effects["requests_that_created"] == 1
    assert effects["logical_payments"] == 1
    assert effects["payment_intent_rows_total"] == 1
    assert effects["provider_payments"] <= 1
    # Every racer received the SAME intent rather than an error.
    assert effects["distinct_intent_ids_returned"] == 1


async def test_conflicting_idempotency_key_is_denied_under_concurrency():
    result = await _run("pg_conflicting_idempotency_key")

    assert result.status is AttackStatus.BLOCKED, result.error
    effects = result.observed_effects
    assert effects["requests_that_created"] == 1
    assert effects["refused_with_idempotency_conflict"] == 1
    assert effects["payment_intent_rows_total"] == 1
    # The loser did not spend its own authorization discovering it lost.
    assert effects["authorizations_consumed"] == 1
    assert effects["loser_authorization_left_unspent"] is True


async def test_two_workers_cannot_both_claim_one_outbox_event():
    result = await _run("pg_outbox_double_claim")

    assert result.status is AttackStatus.BLOCKED, result.error
    effects = result.observed_effects
    assert effects["concurrent_workers"] == RACERS
    assert effects["successful_claims"] == 1
    assert effects["distinct_claim_owners"] == 1
    # A double claim would show two attempt increments for one turn.
    assert effects["attempt_counts"] == [1]


async def test_conflicting_terminal_webhooks_apply_exactly_one_transition():
    result = await _run("pg_concurrent_terminal_webhook_race")

    assert result.status is AttackStatus.BLOCKED, result.error
    effects = result.observed_effects
    assert effects["transitions_applied"] == 1
    assert effects["final_state_is_terminal"] is True
    assert effects["logical_payments"] == 1


async def test_concurrent_audit_appends_stay_contiguous_and_verify():
    result = await _run("pg_concurrent_audit_append")

    assert result.status is AttackStatus.BLOCKED, result.error
    effects = result.observed_effects
    assert effects["events_written"] == RACERS
    assert effects["sequences"] == list(range(RACERS))
    assert effects["sequences_contiguous"] is True
    # The stronger property: contiguous numbering AND a chain that verifies.
    assert effects["chain_verifies"] is True
    assert effects["append_failures"] == []


async def test_every_concurrency_scenario_is_exercised_not_skipped():
    """The whole point: these must actually RUN, not report INCONCLUSIVE."""
    report = await evaluate(
        categories=[AttackCategory.CONCURRENCY.value], iterations=1, include_postgres=True
    )

    assert report.postgres_exercised is True
    inconclusive = [
        (r.scenario_id, r.error) for r in report.results if r.status is AttackStatus.INCONCLUSIVE
    ]
    assert not inconclusive, f"concurrency scenarios did not run: {inconclusive}"

    for result in report.results:
        assert result.backend is Backend.POSTGRES
        assert result.status is AttackStatus.BLOCKED, (result.scenario_id, result.error)

    assert report.metrics.attack_block_rate == 1.0
    assert report.findings == []


async def test_repeated_concurrency_runs_are_reliably_blocked():
    """A race that resolves correctly nine times in ten still fails in production."""
    report = await evaluate(
        scenario_ids=[
            "pg_concurrent_authorization_consumption",
            "pg_concurrent_same_key_payment",
        ],
        iterations=3,
        include_postgres=True,
    )

    assert len(report.results) == 6
    assert report.metrics.attacks_blocked == 6
    assert report.metrics.attacks_not_blocked == 0
    assert report.metrics.bypassed_scenarios == []
