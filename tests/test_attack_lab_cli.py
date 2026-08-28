"""CLI behaviour, and above all its exit codes.

The exit code is the only part of this harness a CI system reads. If it returned
0 when an attack got through, every downstream green badge would be meaningless
— so the failure paths are tested with synthetic reports whose outcome is known
exactly, rather than by hoping a real scenario misbehaves.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from services.attack_lab.evaluation import AttackRunReport
from services.attack_lab.metrics import compute_metrics
from services.attack_lab.models import (
    AttackCategory,
    AttackResult,
    AttackStatus,
    Backend,
    Severity,
)
from services.attack_lab.run import (
    EXIT_OK,
    EXIT_SECURITY_FAILURE,
    EXIT_USAGE,
    build_parser,
    decide_exit_code,
    main,
    render_listing,
)

pytestmark = pytest.mark.attack_lab


def _run(
    *,
    scenario_id: str = "synthetic",
    category: AttackCategory = AttackCategory.TRANSACTION,
    status: AttackStatus = AttackStatus.BLOCKED,
    expected_status: AttackStatus = AttackStatus.BLOCKED,
    critical: bool = False,
    backend: Backend = Backend.SQLITE,
) -> AttackResult:
    return AttackResult(
        scenario_id=scenario_id,
        scenario_name=scenario_id,
        category=category,
        severity=Severity.CRITICAL,
        target_invariants=["SYNTHETIC -> CLI EXIT CODE"],
        backend=backend,
        run_id="test-run",
        iteration=1,
        started_at=datetime.now(timezone.utc),
        duration_ms=1.0,
        execute_ms=1.0,
        status=status,
        expected_status=expected_status,
        blocked=status is AttackStatus.BLOCKED,
        critical=critical,
    )


def _report(results: list[AttackResult], *, postgres_exercised: bool = True) -> AttackRunReport:
    from services.attack_lab.evaluation import derive_findings

    now = datetime.now(timezone.utc)
    return AttackRunReport(
        run_id="test-run",
        iterations=1,
        scenarios_selected=len(results),
        started_at=now,
        completed_at=now,
        duration_ms=0.0,
        postgres_included=True,
        postgres_exercised=postgres_exercised,
        results=results,
        metrics=compute_metrics(results),
        findings=derive_findings(results),
    )


# --------------------------------------------------------------------------- #
# Exit codes
# --------------------------------------------------------------------------- #
def test_exit_code_is_zero_when_every_invariant_holds():
    report = _report(
        [
            _run(scenario_id="a", status=AttackStatus.BLOCKED),
            _run(
                scenario_id="c1",
                category=AttackCategory.BENIGN_CONTROL,
                status=AttackStatus.NOT_BLOCKED,
                expected_status=AttackStatus.NOT_BLOCKED,
            ),
        ]
    )
    assert decide_exit_code(report, require_postgres=False) == EXIT_OK
    assert report.clean


def test_exit_code_fails_when_an_attack_is_not_blocked():
    report = _report([_run(scenario_id="bypassed", status=AttackStatus.NOT_BLOCKED)])
    assert decide_exit_code(report, require_postgres=False) == EXIT_SECURITY_FAILURE
    assert not report.clean
    assert report.findings, "a bypass must produce a finding"


def test_exit_code_fails_when_a_benign_control_is_blocked():
    """Over-refusal is a failure too, or the harness would reward denying everything."""
    report = _report(
        [
            _run(
                scenario_id="control",
                category=AttackCategory.BENIGN_CONTROL,
                status=AttackStatus.BLOCKED,
                expected_status=AttackStatus.NOT_BLOCKED,
            )
        ]
    )
    assert decide_exit_code(report, require_postgres=False) == EXIT_SECURITY_FAILURE


def test_exit_code_fails_when_a_critical_scenario_errors():
    """An unproven critical control is not a passing one."""
    report = _report([_run(scenario_id="critical", status=AttackStatus.ERROR, critical=True)])
    assert report.metrics.attacks_not_blocked == 0
    assert decide_exit_code(report, require_postgres=False) == EXIT_SECURITY_FAILURE


def test_a_non_critical_inconclusive_run_does_not_fail_by_default():
    """A developer with no local PostgreSQL still gets a usable SQLite run."""
    report = _report(
        [
            _run(
                scenario_id="pg_thing",
                status=AttackStatus.INCONCLUSIVE,
                backend=Backend.POSTGRES,
            )
        ],
        postgres_exercised=False,
    )
    assert decide_exit_code(report, require_postgres=False) == EXIT_OK


def test_require_postgres_fails_when_postgres_never_ran():
    report = _report(
        [
            _run(
                scenario_id="pg_thing",
                status=AttackStatus.INCONCLUSIVE,
                backend=Backend.POSTGRES,
            )
        ],
        postgres_exercised=False,
    )
    assert decide_exit_code(report, require_postgres=True) == EXIT_SECURITY_FAILURE


# --------------------------------------------------------------------------- #
# Argument handling
# --------------------------------------------------------------------------- #
def test_listing_shows_every_scenario_with_its_invariants():
    listing = render_listing()
    assert "registered scenarios" in listing
    for scenario_id in (
        "merchant_prompt_injection",
        "authorization_replay",
        "audit_payload_tamper",
        "control_legitimate_payment",
    ):
        assert scenario_id in listing
    assert "REPLAYED APPROVAL -> PAYMENT IMPOSSIBLE" in listing
    assert "[postgres]" in listing


def test_list_exits_zero():
    assert main(["--list"]) == EXIT_OK


def test_no_selection_is_a_usage_error():
    assert main([]) == EXIT_USAGE


def test_zero_iterations_is_a_usage_error():
    assert main(["--all", "--iterations", "0"]) == EXIT_USAGE


def test_an_unknown_category_is_a_usage_error():
    assert main(["--category", "NOT_A_CATEGORY"]) == EXIT_USAGE


def test_an_unknown_scenario_is_a_usage_error():
    assert main(["--scenario", "no_such_scenario"]) == EXIT_USAGE


def test_parser_defaults_to_one_iteration():
    """A harness whose default takes an hour is a harness nobody runs."""
    args = build_parser().parse_args(["--all"])
    assert args.iterations == 1
    assert args.sqlite_only is False


def test_running_a_real_scenario_through_the_cli_succeeds(capsys):
    code = main(["--scenario", "authorization_replay", "--sqlite-only"])
    captured = capsys.readouterr()
    assert code == EXIT_OK
    assert "PACTRA ADVERSARIAL EVALUATION" in captured.out
    assert "AUTHORIZATION_REPLAY_DETECTED" in captured.out


def test_cli_writes_a_json_report(tmp_path, capsys):
    import json

    target = tmp_path / "report.json"
    code = main(
        [
            "--scenario",
            "capability_escalation",
            "--sqlite-only",
            "--quiet",
            "--out",
            str(target),
        ]
    )
    capsys.readouterr()
    assert code == EXIT_OK
    payload = json.loads(target.read_text())
    assert payload["results"][0]["scenario_id"] == "capability_escalation"
    assert payload["results"][0]["status"] == "BLOCKED"


def test_cli_json_flag_prints_machine_readable_output(capsys):
    import json

    code = main(["--scenario", "webhook_forgery", "--sqlite-only", "--quiet", "--json"])
    captured = capsys.readouterr()
    assert code == EXIT_OK
    payload = json.loads(captured.out)
    assert payload["system"] == "PACTRA"
    assert payload["metrics"]["attacks_blocked"] == 1
