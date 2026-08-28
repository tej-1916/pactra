"""CLI: ``python -m services.attack_lab.run``.

    --list                       what is registered, and what each one targets
    --all                        run everything
    --scenario ID [--scenario ID]
    --category TRANSACTION       one or more benchmark groups
    --iterations N               repeat the selection N times (default 1)
    --json                       machine-readable report on stdout
    --out PATH                   also write the JSON report to a file
    --sqlite-only                skip the PostgreSQL concurrency scenarios
    --require-postgres           fail if PostgreSQL scenarios could not run

EXIT CODES, AND WHY THEY ARE WHAT THEY ARE
------------------------------------------
    0  every hostile scenario was blocked and every critical one was exercised
    1  a security failure: an attack got through, a control was wrongly blocked,
       or a CRITICAL scenario could not be exercised
    2  usage error

A CRITICAL scenario that ERRORs exits non-zero. That is deliberate and it is the
whole reason ``critical`` exists on a scenario: an exception is not a block, and
a critical control that could not be exercised is a critical control that was not
proven. Treating "the harness crashed" as success is how a green CI badge stops
meaning anything.

An INCONCLUSIVE run does NOT fail by default — a developer without a local
PostgreSQL should still get a useful SQLite run — but it is printed loudly, and
``--require-postgres`` turns it into a failure for CI, where the server is
supposed to be there.

Default iteration count is 1. A harness whose default takes an hour is a harness
nobody runs.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

from services.attack_lab.evaluation import AttackRunReport, evaluate
from services.attack_lab.models import AttackCategory, Backend
from services.attack_lab.registry import UnknownScenario, load_registry
from services.attack_lab.report import render_json, render_text, write_report

EXIT_OK = 0
EXIT_SECURITY_FAILURE = 1
EXIT_USAGE = 2

#: Default location for a written report. Gitignored: a generated benchmark
#: artifact committed by default becomes a number nobody re-measures.
DEFAULT_REPORT_DIR = Path("reports/attack-lab")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m services.attack_lab.run",
        description="PACTRA adversarial attack lab and evaluation harness.",
    )
    selection = parser.add_argument_group("selection")
    selection.add_argument("--list", action="store_true", help="list registered scenarios")
    selection.add_argument("--all", action="store_true", help="run every registered scenario")
    selection.add_argument(
        "--scenario",
        action="append",
        default=[],
        metavar="ID",
        help="run one scenario by id (repeatable)",
    )
    selection.add_argument(
        "--category",
        action="append",
        default=[],
        metavar="NAME",
        help=f"run a benchmark group: {', '.join(c.value for c in AttackCategory)}",
    )

    execution = parser.add_argument_group("execution")
    execution.add_argument(
        "--iterations",
        type=int,
        default=1,
        metavar="N",
        help="repeat the selection N times (default 1)",
    )
    execution.add_argument(
        "--sqlite-only",
        action="store_true",
        help="skip PostgreSQL concurrency scenarios (they report INCONCLUSIVE)",
    )
    execution.add_argument(
        "--require-postgres",
        action="store_true",
        help="exit non-zero if the PostgreSQL scenarios could not be exercised",
    )

    output = parser.add_argument_group("output")
    output.add_argument("--json", action="store_true", help="print the JSON report")
    output.add_argument(
        "--out",
        type=Path,
        default=None,
        metavar="PATH",
        help=f"write the JSON report to PATH (suggested: {DEFAULT_REPORT_DIR}/…)",
    )
    output.add_argument("--quiet", action="store_true", help="suppress the text report")
    return parser


def render_listing() -> str:
    registry = load_registry()
    lines = [f"{len(registry)} registered scenarios", ""]
    for category in AttackCategory:
        scenarios = registry.list(category=category)
        if not scenarios:
            continue
        lines.append(f"{category.value}  ({len(scenarios)})")
        for scenario in scenarios:
            backend = "  [postgres]" if scenario.backend is Backend.POSTGRES else ""
            critical = "  [critical]" if scenario.critical else ""
            lines.append(f"  {scenario.id:42} {scenario.severity.value:<8}{backend}{critical}")
            lines.append(
                f"      expects {scenario.expected_status.value}",
            )
            for invariant in scenario.target_invariants:
                lines.append(f"      invariant: {invariant}")
        lines.append("")
    return "\n".join(lines)


def decide_exit_code(report: AttackRunReport, *, require_postgres: bool) -> int:
    """Translate a report into a CI verdict.

    Four things fail the run, and each is a genuine security statement:
    an attack that went through; a benign control that was refused; a CRITICAL
    scenario that did not reach its expected outcome (including by erroring);
    and — only when asked — PostgreSQL scenarios that never ran.
    """
    metrics = report.metrics

    if metrics.attacks_not_blocked > 0:
        return EXIT_SECURITY_FAILURE
    if metrics.controls_blocked > 0:
        return EXIT_SECURITY_FAILURE
    if metrics.critical_failures:
        return EXIT_SECURITY_FAILURE
    if require_postgres and not report.postgres_exercised:
        return EXIT_SECURITY_FAILURE
    return EXIT_OK


async def run(args: argparse.Namespace) -> int:
    registry = load_registry()

    if args.list:
        print(render_listing())
        return EXIT_OK

    if not (args.all or args.scenario or args.category):
        build_parser().print_usage(sys.stderr)
        print(
            "\nnothing selected: pass --all, --scenario ID, --category NAME, or --list",
            file=sys.stderr,
        )
        return EXIT_USAGE

    if args.iterations < 1:
        print("--iterations must be at least 1", file=sys.stderr)
        return EXIT_USAGE

    for name in args.category:
        try:
            AttackCategory(name.upper())
        except ValueError:
            valid = ", ".join(c.value for c in AttackCategory)
            print(f"unknown category {name!r}; valid: {valid}", file=sys.stderr)
            return EXIT_USAGE

    try:
        report = await evaluate(
            registry=registry,
            scenario_ids=args.scenario or None,
            categories=args.category or None,
            iterations=args.iterations,
            include_postgres=not args.sqlite_only,
        )
    except UnknownScenario as unknown:
        print(f"{unknown}", file=sys.stderr)
        print(
            "run `--list` to see registered scenario ids",
            file=sys.stderr,
        )
        return EXIT_USAGE

    if not args.quiet:
        print(render_text(report))
    if args.json:
        print(render_json(report))
    if args.out is not None:
        written = write_report(report, args.out)
        print(f"\nJSON report written to {written}", file=sys.stderr)

    exit_code = decide_exit_code(report, require_postgres=args.require_postgres)
    if exit_code != EXIT_OK and args.require_postgres and not report.postgres_exercised:
        print(
            "\n--require-postgres was set but no PostgreSQL scenario reached a verdict",
            file=sys.stderr,
        )
    return exit_code


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return asyncio.run(run(args))


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
