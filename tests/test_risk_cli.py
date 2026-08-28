"""The CLI: deterministic output, honest exit codes, no authority.

The exit-code tests carry the most weight here. An exit code is what CI reads,
and the two mistakes available are opposite: failing on a HIGH risk score (which
would make the advisory layer a gate, and create pressure to report a flattering
number), or passing when part of the corpus silently did not run (which makes a
green result meaningless).
"""

from __future__ import annotations

import json
import uuid

import pytest
from services.risk_engine.config import DEFAULT_RISK_CONFIG, ENGINE_VERSION, HEURISTIC_VERSION
from services.risk_engine.heuristic import FACTOR_RULES
from services.risk_engine.run import (
    EXIT_FAILURE,
    EXIT_OK,
    EXIT_USAGE,
    build_parser,
    main,
    render_config,
    render_corpus,
)
from services.risk_engine.scenarios import RISK_SCENARIOS, SYNTHETIC_DATA_DISCLOSURE


# --------------------------------------------------------------------------- #
# Usage
# --------------------------------------------------------------------------- #
def test_no_selection_is_a_usage_error(capsys):
    assert main([]) == EXIT_USAGE
    assert "nothing selected" in capsys.readouterr().err


def test_mission_and_evaluate_are_mutually_exclusive(capsys):
    assert main(["--mission", str(uuid.uuid4()), "--evaluate"]) == EXIT_USAGE
    assert "mutually exclusive" in capsys.readouterr().err


def test_a_non_uuid_mission_is_a_usage_error(capsys):
    assert main(["--mission", "not-a-uuid"]) == EXIT_USAGE
    assert "must be a UUID" in capsys.readouterr().err


def test_a_zero_iteration_count_is_a_usage_error(capsys):
    assert main(["--evaluate", "--iterations", "0"]) == EXIT_USAGE
    assert "at least 1" in capsys.readouterr().err


def test_the_parser_exposes_no_flag_that_changes_a_weight():
    """Server-owned weights that a CLI switch could adjust would be
    operator-owned at exactly the moment somebody wanted a lower score."""
    options = {option for action in build_parser()._actions for option in action.option_strings}
    for forbidden in (
        "--weight",
        "--threshold",
        "--review-threshold",
        "--score",
        "--band",
        "--saturation",
        "--config",
        "--set",
    ):
        assert forbidden not in options, f"the CLI exposes {forbidden}"


def test_the_parser_exposes_no_flag_that_could_move_money():
    options = {option for action in build_parser()._actions for option in action.option_strings}
    for forbidden in ("--pay", "--execute", "--authorize", "--approve", "--consume"):
        assert forbidden not in options


# --------------------------------------------------------------------------- #
# --list
# --------------------------------------------------------------------------- #
def test_list_names_every_scenario_with_its_label(capsys):
    assert main(["--list"]) == EXIT_OK
    out = capsys.readouterr().out
    for scenario in RISK_SCENARIOS:
        assert scenario.id in out
        assert scenario.label.value in out


def test_list_leads_with_the_synthetic_disclosure():
    rendered = render_corpus()
    assert SYNTHETIC_DATA_DISCLOSURE in rendered
    assert rendered.index(SYNTHETIC_DATA_DISCLOSURE) < rendered.index(RISK_SCENARIOS[0].id)


def test_list_is_deterministic():
    assert render_corpus() == render_corpus()


# --------------------------------------------------------------------------- #
# --show-config
# --------------------------------------------------------------------------- #
def test_show_config_prints_every_factor_and_its_weight(capsys):
    assert main(["--show-config"]) == EXIT_OK
    out = capsys.readouterr().out
    for rule in FACTOR_RULES:
        assert rule.code in out
    assert ENGINE_VERSION in out
    assert HEURISTIC_VERSION in out


def test_show_config_states_that_the_weights_cannot_be_changed():
    rendered = render_config()
    assert "Server-owned and frozen" in rendered
    assert "No CLI flag" in rendered


def test_show_config_reports_the_operating_point_the_engine_uses(capsys):
    main(["--show-config"])
    out = capsys.readouterr().out
    assert f"review threshold       {DEFAULT_RISK_CONFIG.review_threshold}" in out


def test_show_config_is_deterministic():
    assert render_config() == render_config()


# --------------------------------------------------------------------------- #
# --evaluate
# --------------------------------------------------------------------------- #
@pytest.mark.slow
def test_evaluate_exits_zero_on_a_fully_executed_corpus(capsys):
    assert main(["--evaluate"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "EVALUATION REPORT" in out
    assert "risk detection rate" in out
    assert "false positive rate" in out
    assert "false negative rate" in out


@pytest.mark.slow
def test_evaluate_never_calls_the_score_a_fraud_probability(capsys):
    """The one phrase this report must not contain."""
    main(["--evaluate"])
    out = capsys.readouterr().out.lower()
    assert "fraud probability" not in out.replace("not a fraud probability", "")
    assert "normalized risk index" in out or "not a fraud probability" in out


@pytest.mark.slow
def test_evaluate_prints_the_disclosures_before_any_number(capsys):
    main(["--evaluate"])
    out = capsys.readouterr().out
    assert out.index("DATA DISCLOSURE") < out.index("MEASURED METRICS")
    assert out.index("SCORE SEMANTICS") < out.index("MEASURED METRICS")
    assert "ADVISORY BOUNDARY" in out


@pytest.mark.slow
def test_evaluate_distinguishes_its_metric_from_the_attack_block_rate(capsys):
    """Conflating them would let an advisory heuristic's accuracy be read as a
    security property."""
    main(["--evaluate"])
    out = capsys.readouterr().out
    assert "risk_detection_rate is NOT attack_block_rate" in out


@pytest.mark.slow
def test_evaluate_emits_valid_json_and_writes_a_report(tmp_path, capsys):
    target = tmp_path / "risk-run.json"
    assert main(["--evaluate", "--json", "--quiet", "--out", str(target)]) == EXIT_OK

    payload = json.loads(capsys.readouterr().out)
    assert payload["engine_version"] == ENGINE_VERSION
    assert payload["model_version"] == HEURISTIC_VERSION
    assert "SYNTHETIC" in payload["data_disclosure"]
    assert payload["metrics"]["review_threshold"] == DEFAULT_RISK_CONFIG.review_threshold
    assert len(payload["outcomes"]) == len(RISK_SCENARIOS)

    assert target.exists()
    assert json.loads(target.read_text())["run_id"] == payload["run_id"]


@pytest.mark.slow
def test_evaluate_reports_latency_as_harness_local(capsys):
    main(["--evaluate"])
    out = capsys.readouterr().out
    assert "harness-local" in out
    assert "KL-07" in out
    assert "not a" in out and "deployed-enforcement figure" in out


@pytest.mark.slow
def test_a_high_risk_result_does_not_fail_the_run():
    """A measurement that punished an honest bad number would create pressure to
    report a dishonest good one. Several corpus cases score CRITICAL; the run
    still exits 0 because nothing failed to execute."""
    assert main(["--evaluate", "--quiet"]) == EXIT_OK


@pytest.mark.slow
def test_an_errored_scenario_fails_the_run(monkeypatch, capsys):
    """A corpus that did not fully execute must not report success."""
    import services.risk_engine.evaluation as evaluation

    original = evaluation.run_scenario

    async def _one_breaks(scenario, *, iteration, config):
        result = await original(scenario, iteration=iteration, config=config)
        if scenario.id == "benign_low_value":
            return result.model_copy(update={"error": "injected failure"})
        return result

    monkeypatch.setattr(evaluation, "run_scenario", _one_breaks)
    assert main(["--evaluate", "--quiet"]) == EXIT_FAILURE
    assert "did not fully execute" in capsys.readouterr().err


@pytest.mark.slow
def test_a_non_reproducible_score_fails_the_run(monkeypatch, capsys):
    """Determinism is a claim the harness can check for free, so a drift must
    not pass silently."""
    import services.risk_engine.evaluation as evaluation

    original = evaluation.run_scenario

    async def _drifts(scenario, *, iteration, config):
        result = await original(scenario, iteration=iteration, config=config)
        if scenario.id == "benign_low_value" and iteration == 2:
            return result.model_copy(update={"score": result.score + 0.01})
        return result

    monkeypatch.setattr(evaluation, "run_scenario", _drifts)
    assert main(["--evaluate", "--iterations", "2", "--quiet"]) == EXIT_FAILURE
    assert "did not reproduce" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# --mission
# --------------------------------------------------------------------------- #
def test_assessing_an_absent_mission_fails_without_scoring_it(tmp_path, capsys):
    """A LOW score for a mission that does not exist is the wrong default."""
    import asyncio

    from apps.api.db import models  # noqa: F401  (register metadata)
    from apps.api.db.base import Base
    from sqlalchemy.ext.asyncio import create_async_engine

    url = f"sqlite+aiosqlite:///{tmp_path / 'risk-cli.db'}"

    async def _schema():
        engine = create_async_engine(url, future=True)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        await engine.dispose()

    asyncio.run(_schema())

    code = main(["--mission", str(uuid.uuid4()), "--database-url", url])
    assert code == EXIT_FAILURE
    assert "does not exist" in capsys.readouterr().err


def test_assessing_a_real_mission_prints_a_reproducible_advisory_report(tmp_path, capsys):
    import asyncio

    from apps.api.db import models  # noqa: F401  (register metadata)
    from apps.api.db.base import Base
    from apps.api.db.session import configure_sqlite_transactions
    from packages.schemas.domain import CreateMissionRequest, MissionConstraints
    from services.agent_orchestrator.merchants.mock_merchants import MockMerchantA
    from services.agent_orchestrator.orchestrator import Orchestrator
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    url = f"sqlite+aiosqlite:///{tmp_path / 'risk-cli-mission.db'}"

    async def _seed() -> str:
        engine = configure_sqlite_transactions(create_async_engine(url, future=True))
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            mission = await Orchestrator(merchants=[MockMerchantA()]).run(
                session,
                CreateMissionRequest(
                    quantity=1,
                    constraints=MissionConstraints(
                        category="wireless_earbuds",
                        soft_budget_inr=4000,
                        hard_limit_inr=4500,
                        min_rating=4.2,
                        currency="INR",
                    ),
                ),
            )
            mission_id = str(mission.id)
            await session.commit()
        await engine.dispose()
        return mission_id

    mission_id = asyncio.run(_seed())

    assert main(["--mission", mission_id, "--database-url", url]) == EXIT_OK
    first = capsys.readouterr().out
    assert "PACTRA RISK ASSESSMENT" in first
    assert "ADVISORY ONLY" in first
    assert "NOT a fraud probability" in first
    assert "deterministic policy decision: REQUIRE_APPROVAL" in first

    assert main(["--mission", mission_id, "--database-url", url]) == EXIT_OK
    second = capsys.readouterr().out

    def _without_ids(text: str) -> list[str]:
        return [
            line
            for line in text.splitlines()
            if not line.startswith(("assessment  ", "evaluated_at"))
        ]

    assert _without_ids(first) == _without_ids(second)


def test_assessing_a_mission_writes_no_audit_event(tmp_path, capsys):
    """A developer inspecting a mission must not silently alter its history."""
    import asyncio

    from apps.api.db import models  # noqa: F401  (register metadata)
    from apps.api.db.base import Base
    from apps.api.db.models import AuditEventRow
    from apps.api.db.session import configure_sqlite_transactions
    from packages.schemas.domain import CreateMissionRequest, MissionConstraints
    from services.agent_orchestrator.merchants.mock_merchants import MockMerchantA
    from services.agent_orchestrator.orchestrator import Orchestrator
    from sqlalchemy import func, select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    url = f"sqlite+aiosqlite:///{tmp_path / 'risk-cli-readonly.db'}"

    async def _seed() -> tuple[str, int]:
        engine = configure_sqlite_transactions(create_async_engine(url, future=True))
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            mission = await Orchestrator(merchants=[MockMerchantA()]).run(
                session,
                CreateMissionRequest(
                    quantity=1,
                    constraints=MissionConstraints(
                        category="wireless_earbuds",
                        soft_budget_inr=4000,
                        hard_limit_inr=4500,
                        min_rating=4.2,
                        currency="INR",
                    ),
                ),
            )
            mission_id = str(mission.id)
            await session.commit()
        async with maker() as session:
            count = int(
                (
                    await session.execute(select(func.count()).select_from(AuditEventRow))
                ).scalar_one()
            )
        await engine.dispose()
        return mission_id, count

    async def _count() -> int:
        engine = configure_sqlite_transactions(create_async_engine(url, future=True))
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            count = int(
                (
                    await session.execute(select(func.count()).select_from(AuditEventRow))
                ).scalar_one()
            )
        await engine.dispose()
        return count

    mission_id, before = asyncio.run(_seed())
    for _ in range(3):
        assert main(["--mission", mission_id, "--database-url", url, "--quiet"]) == EXIT_OK
    assert asyncio.run(_count()) == before


def test_mission_json_mode_emits_a_typed_assessment(tmp_path, capsys):
    import asyncio

    from apps.api.db import models  # noqa: F401  (register metadata)
    from apps.api.db.base import Base
    from apps.api.db.session import configure_sqlite_transactions
    from packages.schemas.domain import CreateMissionRequest, MissionConstraints
    from services.agent_orchestrator.merchants.mock_merchants import MockMerchantA
    from services.agent_orchestrator.orchestrator import Orchestrator
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    url = f"sqlite+aiosqlite:///{tmp_path / 'risk-cli-json.db'}"

    async def _seed() -> str:
        engine = configure_sqlite_transactions(create_async_engine(url, future=True))
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            mission = await Orchestrator(merchants=[MockMerchantA()]).run(
                session,
                CreateMissionRequest(
                    quantity=1,
                    constraints=MissionConstraints(
                        category="wireless_earbuds",
                        soft_budget_inr=4000,
                        hard_limit_inr=4500,
                        min_rating=4.2,
                        currency="INR",
                    ),
                ),
            )
            mission_id = str(mission.id)
            await session.commit()
        await engine.dispose()
        return mission_id

    mission_id = asyncio.run(_seed())
    assert main(["--mission", mission_id, "--database-url", url, "--json", "--quiet"]) == EXIT_OK

    payload = json.loads(capsys.readouterr().out)
    assert payload["advisory"] is True
    assert payload["score_semantics"] == "NORMALIZED_RISK_INDEX"
    assert payload["engine_version"] == ENGINE_VERSION
    assert 0.0 <= payload["score"] <= 1.0
    assert "nonce" not in json.dumps(payload)
