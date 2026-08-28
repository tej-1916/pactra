"""CLI: ``python -m services.risk_engine.run``.

    --mission UUID          assess one mission from the configured database
    --evaluate              run the labelled synthetic evaluation corpus
    --iterations N          repeat the corpus N times (default 1)
    --list                  the corpus, with each case's authored label
    --show-config           every weight and threshold, with its factor
    --json                  machine-readable output
    --out PATH              also write the JSON report to a file
    --database-url URL      override the database for --mission

WHAT THIS CLI CANNOT DO, BY CONSTRUCTION
------------------------------------------
There is no flag that authorizes a payment, approves an authorization, changes a
policy, or overrides a decision — and there is no flag that changes a WEIGHT.
``--show-config`` prints the configuration; nothing writes it. Weights are
server-owned, and a CLI switch that adjusted them would make them
operator-owned at exactly the moment somebody wanted a lower score.

``--mission`` opens a session and calls ``assess_mission``, which issues only
SELECTs. It does not record a ``RISK_ASSESSED`` event: recording is an explicit
act, and a developer inspecting a mission should not silently write to its audit
chain. Recording is available through ``POST /missions/{id}/risk/assess``.

EXIT CODES
----------
    0  the command completed and, for --evaluate, every scenario was measured
    1  an evaluation run had an errored scenario, a non-reproducible score, or
       (for --mission) the mission does not exist
    2  usage error

An errored scenario fails the run rather than being averaged away. Phase 6's
reasoning applies unchanged: a case that did not execute proved nothing, and a
harness that returns success while part of its corpus silently failed is a
harness whose green result means nothing.

A poor detection rate does NOT fail the run. This is a measurement, and an exit
code that punished an honest bad number is an exit code that creates pressure to
report a dishonest good one.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from services.risk_engine.config import DEFAULT_RISK_CONFIG, ENGINE_VERSION, HEURISTIC_VERSION
from services.risk_engine.engine import assess_mission
from services.risk_engine.features import MissionNotFound
from services.risk_engine.heuristic import FACTOR_RULES
from services.risk_engine.report import render_assessment, render_json, render_text, write_report
from services.risk_engine.scenarios import RISK_SCENARIOS, SYNTHETIC_DATA_DISCLOSURE

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_USAGE = 2

#: Gitignored, like the attack lab's. A generated benchmark artifact committed
#: by default becomes a number nobody re-measures.
DEFAULT_REPORT_DIR = Path("reports/risk-engine")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m services.risk_engine.run",
        description=(
            "PACTRA advisory risk engine. Scores, explains, and recommends. Authorizes nothing."
        ),
    )
    selection = parser.add_argument_group("what to do")
    selection.add_argument("--mission", metavar="UUID", help="assess one mission by id")
    selection.add_argument(
        "--evaluate", action="store_true", help="run the labelled synthetic corpus"
    )
    selection.add_argument(
        "--list", action="store_true", help="list the evaluation corpus and its labels"
    )
    selection.add_argument(
        "--show-config",
        action="store_true",
        help="print every weight and threshold, with the factor that reads it",
    )

    execution = parser.add_argument_group("execution")
    execution.add_argument(
        "--iterations", type=int, default=1, metavar="N", help="repeat the corpus N times"
    )
    execution.add_argument(
        "--database-url",
        default=None,
        metavar="URL",
        help="async SQLAlchemy URL for --mission (defaults to app settings)",
    )

    output = parser.add_argument_group("output")
    output.add_argument("--json", action="store_true", help="print JSON")
    output.add_argument(
        "--out",
        type=Path,
        default=None,
        metavar="PATH",
        help=f"write the JSON evaluation report to PATH (suggested: {DEFAULT_REPORT_DIR}/…)",
    )
    output.add_argument("--quiet", action="store_true", help="suppress the text report")
    return parser


def render_corpus() -> str:
    """The corpus, with each case's authored label stated up front."""
    lines = [
        f"{len(RISK_SCENARIOS)} evaluation scenario families",
        "",
        "DATASET_TYPE = SYNTHETIC      LABEL_SOURCE = AUTHORED",
        SYNTHETIC_DATA_DISCLOSURE,
        "",
    ]
    for scenario in RISK_SCENARIOS:
        lines.append(f"  [{scenario.label.value:<6}] {scenario.id}")
        lines.append(f"      {scenario.name}  ({scenario.category.value})")
        lines.append(f"      {scenario.description}")
    return "\n".join(lines)


def render_config() -> str:
    """Every tunable, and which factor reads it.

    Printed so the scoring rules can be audited without reading the source. A
    weight nobody can see is a weight nobody can challenge.
    """
    config = DEFAULT_RISK_CONFIG
    lines = [
        f"engine {ENGINE_VERSION}   heuristic {HEURISTIC_VERSION}",
        "",
        "Server-owned and frozen. No CLI flag, request field, or capability can "
        "change any value below.",
        "",
        f"  saturation_points      {config.saturation_points}",
        f"  band MEDIUM at         {config.band_medium_at}",
        f"  band HIGH at           {config.band_high_at}",
        f"  band CRITICAL at       {config.band_critical_at}",
        f"  review threshold       {config.review_threshold}",
        f"  min history obs        {config.min_history_observations}",
        f"  min merchant payments  {config.min_merchant_payment_history}",
        "",
        f"{len(FACTOR_RULES)} scoring factors:",
    ]
    for rule in FACTOR_RULES:
        weight = getattr(config, rule.weight_field)
        bounds = "  ".join(f"{name}={getattr(config, name)}" for name in rule.config_fields()[1:])
        lines.append(f"  {rule.code}")
        lines.append(
            f"      feature={rule.feature}  shape={rule.shape.value}  weight={weight}"
            + (f"  {bounds}" if bounds else "")
        )
    return "\n".join(lines)


async def _assess_one(args: argparse.Namespace) -> int:
    try:
        mission_id = uuid.UUID(args.mission)
    except ValueError:
        print(f"--mission must be a UUID; got {args.mission!r}", file=sys.stderr)
        return EXIT_USAGE

    from apps.api.pactra.config import get_settings

    url = args.database_url or get_settings().database_url
    engine = create_async_engine(url, future=True)
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            try:
                assessment = await assess_mission(session, mission_id)
            except MissionNotFound as missing:
                print(str(missing), file=sys.stderr)
                return EXIT_FAILURE
    finally:
        await engine.dispose()

    if not args.quiet:
        print(render_assessment(assessment))
    if args.json:
        import json

        print(json.dumps(assessment.model_dump(mode="json"), indent=2, sort_keys=True))
    return EXIT_OK


async def _evaluate(args: argparse.Namespace) -> int:
    if args.iterations < 1:
        print("--iterations must be at least 1", file=sys.stderr)
        return EXIT_USAGE

    from services.risk_engine.evaluation import evaluate

    report = await evaluate(iterations=args.iterations)

    if not args.quiet:
        print(render_text(report))
    if args.json:
        print(render_json(report))
    if args.out is not None:
        written = write_report(report, args.out)
        print(f"\nJSON report written to {written}", file=sys.stderr)

    metrics = report.metrics
    if metrics.errors > 0:
        print(
            f"\n{metrics.errors} scenario run(s) errored and were excluded from every "
            "rate; the corpus did not fully execute",
            file=sys.stderr,
        )
        return EXIT_FAILURE
    if not metrics.deterministic_across_iterations:
        print(
            "\nscores did not reproduce across iterations: "
            f"{', '.join(metrics.nondeterministic_scenarios)}",
            file=sys.stderr,
        )
        return EXIT_FAILURE
    return EXIT_OK


async def run(args: argparse.Namespace) -> int:
    if args.list:
        print(render_corpus())
        return EXIT_OK
    if args.show_config:
        print(render_config())
        return EXIT_OK
    if args.mission and args.evaluate:
        print("--mission and --evaluate are mutually exclusive", file=sys.stderr)
        return EXIT_USAGE
    if args.mission:
        return await _assess_one(args)
    if args.evaluate:
        return await _evaluate(args)

    build_parser().print_usage(sys.stderr)
    print(
        "\nnothing selected: pass --mission UUID, --evaluate, --list, or --show-config",
        file=sys.stderr,
    )
    return EXIT_USAGE


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(run(build_parser().parse_args(argv)))


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
