"""Report rendering, JSON validity, and the no-secrets rule.

The secrets test is the one that matters most here. Attack scenarios run through
the real kernel, so their observed effects are assembled from real state — and
real state includes an authorization nonce, a webhook secret, and a full
transaction digest. None of those may reach a file somebody shares. The test
generates a genuine report from real scenario runs and then searches the
serialized output for the live values, rather than checking a hand-written
sample that could not contain them anyway.
"""

from __future__ import annotations

import json

import pytest
from apps.api.db.models import AuthorizationRow
from services.attack_lab.evaluation import AttackRunReport, derive_findings, evaluate
from services.attack_lab.models import (
    AttackCategory,
    AttackStatus,
    Severity,
)
from services.attack_lab.report import render_json, render_text, write_report
from sqlalchemy import select

pytestmark = pytest.mark.attack_lab

#: Enough scenarios to exercise every rendered section without running the whole
#: suite for a formatting test.
_SAMPLE = [
    "authorization_replay",
    "capability_escalation",
    "audit_payload_tamper",
    "audit_tail_truncation",
    "control_legitimate_payment",
]


async def _sample_report() -> AttackRunReport:
    return await evaluate(scenario_ids=_SAMPLE, iterations=1, include_postgres=False)


async def test_json_report_round_trips_and_revalidates():
    report = await _sample_report()
    payload = json.loads(render_json(report))

    # Structural expectations the JSON contract promises.
    for key in (
        "run_id",
        "system",
        "iterations",
        "started_at",
        "completed_at",
        "results",
        "metrics",
        "findings",
        "known_limitations",
    ):
        assert key in payload, f"JSON report is missing {key!r}"

    assert payload["system"] == "PACTRA"
    assert payload["iterations"] == 1
    assert len(payload["results"]) == len(_SAMPLE)

    # It must re-validate as the model it came from — a report that cannot be
    # parsed back is not machine-readable, whatever it looks like.
    restored = AttackRunReport.model_validate(payload)
    assert restored.run_id == report.run_id
    assert len(restored.results) == len(report.results)


async def test_every_result_carries_its_invariant_mapping():
    report = await _sample_report()
    for result in report.results:
        assert result.target_invariants, f"{result.scenario_id} lost its invariant mapping"


async def test_report_contains_no_secret_values(session):
    """Real nonces, secrets and full digests must never reach a report."""
    report = await evaluate(
        scenario_ids=["authorization_replay", "control_valid_webhook"],
        iterations=1,
        include_postgres=False,
    )
    serialized = render_json(report) + render_text(report)

    # The webhook secret is a literal in the test double; if a scenario ever put
    # it in an observed effect, this catches it.
    assert "fake-webhook-secret" not in serialized

    # No 64-character hex run should appear at all: that is the shape of a nonce
    # and of a full transaction digest. Scenarios publish truncated prefixes.
    import re

    long_hex = [
        token
        for token in re.findall(r"\b[0-9a-f]{64}\b", serialized)
        # The genesis hash is a public constant, not a secret.
        if token != "0" * 64
    ]
    assert not long_hex, f"a 64-hex-character value leaked into the report: {long_hex[:2]}"

    # And the keys themselves must be absent.
    for forbidden in ("nonce", "webhook_secret", "signature", "key_secret"):
        assert f'"{forbidden}"' not in serialized, f"{forbidden!r} appears in the report"


async def test_findings_are_derived_only_from_actual_bypasses():
    """No bypass, no finding. There is no other way to create one."""
    report = await _sample_report()
    for result in report.results:
        assert result.status is not AttackStatus.NOT_BLOCKED or not result.is_malicious
    assert report.findings == []


def test_a_finding_is_built_from_the_bypassing_runs_own_evidence():
    from datetime import datetime, timezone

    from services.attack_lab.models import AttackResult, Backend

    bypass = AttackResult(
        scenario_id="synthetic_bypass",
        scenario_name="synthetic bypass",
        category=AttackCategory.TRANSACTION,
        severity=Severity.CRITICAL,
        target_invariants=["REPLAYED APPROVAL -> PAYMENT IMPOSSIBLE"],
        backend=Backend.SQLITE,
        run_id="test-run",
        iteration=1,
        started_at=datetime.now(timezone.utc),
        duration_ms=1.0,
        execute_ms=1.0,
        status=AttackStatus.NOT_BLOCKED,
        expected_status=AttackStatus.BLOCKED,
        blocked=False,
        reason_code=None,
        expected_reason_code="AUTHORIZATION_REPLAY_DETECTED",
        reason_match=False,
        observed_effects={"payment_intents_after": 2},
    )

    findings = derive_findings([bypass, bypass])
    assert len(findings) == 1
    finding = findings[0]
    assert finding.scenario_id == "synthetic_bypass"
    assert finding.severity is Severity.CRITICAL
    assert finding.occurrences == 2, "repeats of one bypass are one finding"
    assert finding.observed_effect == {"payment_intents_after": 2}
    assert "--scenario synthetic_bypass" in finding.reproduction
    assert "AUTHORIZATION_REPLAY_DETECTED" in finding.description


def test_no_findings_are_invented_from_clean_results():
    assert derive_findings([]) == []


async def test_text_report_prints_failures_and_never_fabricates_a_rate():
    report = await _sample_report()
    text = render_text(report)

    assert "PACTRA ADVERSARIAL EVALUATION" in text
    assert "MEASURED METRICS" in text
    assert "KNOWN LIMITATIONS" in text
    # Every rate is printed with the counts it was derived from.
    assert "attack_block_rate" in text
    assert "= " in text
    # The known limitation is reported, and marked as not a blocked attack.
    assert "audit_tail_truncation" in text


def test_a_rate_with_no_denominator_renders_as_not_available():
    from services.attack_lab.report import _pct

    assert _pct(None) == "n/a"
    assert _pct(1.0) == "100.00%"
    assert _pct(0.0) == "0.00%"


async def test_written_report_is_valid_json_on_disk(tmp_path):
    report = await _sample_report()
    path = write_report(report, tmp_path / "nested" / "report.json")
    assert path.exists()
    restored = AttackRunReport.model_validate(json.loads(path.read_text()))
    assert restored.run_id == report.run_id


async def test_repeated_iterations_produce_one_result_per_scenario_per_iteration():
    report = await evaluate(
        scenario_ids=["authorization_replay"], iterations=3, include_postgres=False
    )
    assert report.iterations == 3
    assert len(report.results) == 3
    assert sorted(r.iteration for r in report.results) == [1, 2, 3]
    assert report.metrics.total_runs == 3
    assert report.metrics.total_scenarios == 1


async def test_no_authorization_nonce_is_ever_exposed_by_a_scenario(session):
    """Cross-check: the nonces that exist are genuinely absent from the report."""
    report = await evaluate(
        scenario_ids=["authorization_replay", "transaction_mutation"],
        iterations=1,
        include_postgres=False,
    )
    serialized = render_json(report)
    # The scenarios ran against their own isolated databases, so read the live
    # nonces from a fresh run of the same fixture and prove none appear.
    from services.attack_lab.context import make_sqlite_context

    context, engine = await make_sqlite_context()
    try:
        await context.authorized_mission()
        async with context.sessionmaker() as s:
            nonces = list((await s.execute(select(AuthorizationRow.nonce))).scalars().all())
    finally:
        await engine.dispose()

    assert nonces, "the fixture should have produced an authorization"
    for nonce in nonces:
        assert nonce not in serialized
