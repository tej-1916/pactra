"""CLI: ``python -m services.adapters.run``.

    --list                          registered adapters, by family
    --describe ID                   one adapter in full, including its gaps
    --matrix                        the protocol support matrix
    --limitations                   AL-01..AL-07, the adapter-layer boundaries
    --translate ID --file PATH      translate a fixture and print the envelope
    --family NAME                   the family to resolve --translate under
    --protocol-version V            required for --translate; never inferred
    --claimed-id ID                 the identity the fixture claims (default cli)
    --json                          machine-readable output

WHAT THIS CLI CANNOT DO, BY CONSTRUCTION
-----------------------------------------
There is no flag that registers an adapter, changes one's family, changes its
trust, or names a class to import. Registration is a call in
``services/adapters/__init__.py`` and nothing here can add to it — if a caller
could register an adapter, "adapter identity is server-owned" would be a
sentence rather than a property.

There is no flag that authorizes a payment, issues an authorization, or writes a
row. It could not have one: ``translate`` is a synchronous pure function with no
database session, so ``--translate`` prints an envelope and touches nothing.

``--protocol-version`` has no default. A default would be this CLI deciding
which version a payload is, which is exactly the silent reinterpretation the
adapters refuse.

EXIT CODES
----------
    0  the command completed
    1  a translation was refused (the reason code is printed), or a named
       adapter or fixture does not exist
    2  usage error

A refused translation exits 1 because that is what a developer checking a
fixture wants to know. It is NOT a security failure — a boundary refusing a bad
payload is the boundary working — so nothing here should be read as a benchmark.
The security benchmark is ``python -m services.attack_lab.run``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from services.adapters.agents import NOT_IMPLEMENTED_REASON as AGENT_FAMILY_REASON
from services.adapters.errors import AdapterError
from services.adapters.limitations import ADAPTER_LIMITATIONS
from services.adapters.models import AdapterFamily, SourceIdentity
from services.adapters.payment_rails import RAIL_REGISTRY_MODULE, describe_payment_rails
from services.adapters.registry import load_registry
from services.adapters.support import PROTOCOL_SUPPORT
from services.adapters.translate import translate

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_USAGE = 2

CLI_CHANNEL = "cli"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m services.adapters.run",
        description=(
            "PACTRA protocol adapters. Translates external payloads into canonical, "
            "still-untrusted candidates. Authorizes nothing and executes nothing."
        ),
    )
    what = parser.add_argument_group("what to do")
    what.add_argument("--list", action="store_true", help="list registered adapters")
    what.add_argument("--describe", metavar="ID", help="describe one adapter")
    what.add_argument("--matrix", action="store_true", help="print the protocol support matrix")
    what.add_argument(
        "--limitations", action="store_true", help="print the adapter-layer limitations"
    )
    what.add_argument("--translate", metavar="ID", help="translate a fixture with this adapter")

    translation = parser.add_argument_group("translation")
    translation.add_argument("--file", type=Path, metavar="PATH", help="JSON fixture to translate")
    translation.add_argument(
        "--family",
        metavar="NAME",
        help=f"family to resolve under: {', '.join(f.value for f in AdapterFamily)}",
    )
    translation.add_argument(
        "--protocol-version",
        metavar="V",
        help="protocol version of the fixture (required; never inferred)",
    )
    translation.add_argument(
        "--claimed-id",
        metavar="ID",
        default="cli-caller",
        help="the identity the fixture claims (a claim, never authenticated)",
    )

    parser.add_argument("--json", action="store_true", help="machine-readable output")
    return parser


# --------------------------------------------------------------------------- #
# Renderers
# --------------------------------------------------------------------------- #
def render_listing() -> str:
    registry = load_registry()
    lines = [f"{len(registry)} registered adapters", ""]
    for family in AdapterFamily:
        descriptors = registry.list(family=family)
        if not descriptors:
            continue
        lines.append(f"{family.display_name}  ({len(descriptors)})")
        for descriptor in descriptors:
            lines.append(
                f"  {descriptor.adapter_id:<32} {descriptor.protocol_name} "
                f"{descriptor.protocol_version}  [{descriptor.status.value}]"
            )
        lines.append("")

    lines.append("PaymentRailAdapter  (execution family — not in this registry)")
    for name, status in describe_payment_rails():
        lines.append(f"  {name:<32} [{status.value}]")
    lines.append(f"  resolved by {RAIL_REGISTRY_MODULE}, under the payment.execute capability")
    lines.append("")
    lines.append("AgentCommunicationAdapter  (declared, NOT implemented)")
    lines.append(f"  {AGENT_FAMILY_REASON}")
    return "\n".join(lines)


def render_description(adapter_id: str) -> str:
    descriptor = load_registry().describe(adapter_id)
    entry = next(
        (e for e in PROTOCOL_SUPPORT if e.adapter_id == descriptor.adapter_id),
        None,
    )
    lines = [
        f"{descriptor.adapter_id}",
        f"  family              {descriptor.family.display_name}",
        f"  protocol            {descriptor.protocol_name}",
        f"  protocol version    {descriptor.protocol_version}",
        f"  supported versions  {', '.join(descriptor.supported_protocol_versions)}",
        f"  adapter version     {descriptor.adapter_version}",
        f"  status              {descriptor.status.value}",
        f"  emits authority     {descriptor.emits_authority.name} (ceiling)",
        f"  emits trust         {descriptor.emits_trust.value}",
        "",
        f"  {descriptor.summary}",
    ]
    if entry is not None:
        lines += [
            "",
            f"  SUPPORTED:     {entry.supported}",
            f"  NOT SUPPORTED: {entry.not_supported}",
        ]
    return "\n".join(lines)


def render_matrix() -> str:
    lines = ["Protocol support matrix", ""]
    header = f"  {'PROTOCOL':<32} {'FAMILY':<28} {'STATUS':<12} ADAPTER"
    lines += [header, "  " + "-" * (len(header) - 2)]
    for entry in PROTOCOL_SUPPORT:
        family = entry.family.display_name if entry.family else "(unassigned)"
        lines.append(
            f"  {entry.protocol:<32} {family:<28} {entry.status.value:<12} "
            f"{entry.adapter_id or '-'}"
        )
    lines += ["", "  Statuses are IMPLEMENTED / PARTIAL / PLANNED / NOT_APPLICABLE."]
    lines.append("  There is deliberately no 'SUPPORTED': it is the word that means whatever")
    lines.append("  the reader hopes. Run --describe ID for what each adapter does NOT do.")
    return "\n".join(lines)


def render_limitations() -> str:
    lines = ["Adapter-layer limitations (AL-*)", ""]
    for limitation in ADAPTER_LIMITATIONS:
        lines.append(f"  {limitation.id}")
        lines.append(f"    {limitation.title}")
        lines.append(f"    {limitation.detail}")
        if limitation.demonstrated_by:
            lines.append(f"    demonstrated by attack-lab scenario: {limitation.demonstrated_by}")
        lines.append("")
    lines.append("  KL-01..KL-07 (security) and RL-01..RL-09 (risk measurement) are separate")
    lines.append("  lists, unchanged and unfixed by Phase 8.")
    return "\n".join(lines)


def render_envelope(envelope: object) -> str:
    from services.adapters.models import AdapterEnvelope

    assert isinstance(envelope, AdapterEnvelope)  # noqa: S101 - narrowing, not a control
    lines = [
        f"{envelope.adapter_id}  ->  {type(envelope.canonical_payload).__name__}",
        "",
        f"  family            {envelope.adapter_family.display_name}",
        f"  protocol          {envelope.protocol_name} {envelope.protocol_version}",
        f"  adapter version   {envelope.adapter_version}",
        f"  claimed source    {envelope.source_identity.claimed_id} "
        f"(authenticated={envelope.source_identity.authenticated})",
        f"  source trust      {envelope.source_trust.value}",
        f"  source authority  {envelope.source_authority.name}",
        f"  taint             {envelope.taint}",
        f"  raw reference     {envelope.raw_reference}  ({envelope.raw_byte_length} bytes)",
        f"  fingerprint       {envelope.canonical_fingerprint()}",
        "",
        "  canonical payload",
    ]
    payload = json.loads(envelope.canonical_payload.model_dump_json())
    for line in json.dumps(payload, indent=2, sort_keys=True).splitlines():
        lines.append(f"    {line}")
    lines += ["", f"  provenance ({len(envelope.provenance)} fields)"]
    for name, meta in sorted(envelope.provenance.items()):
        lines.append(
            f"    {name:<34} {meta.authority.name:<16} {meta.trust.value:<12} "
            f"tainted={meta.tainted}"
        )
    if envelope.warnings:
        lines += ["", "  warnings"]
        for warning in envelope.warnings:
            lines.append(f"    {warning.code.value}")
            lines.append(f"      {warning.detail}")
    lines += [
        "",
        "  NOTHING WAS WRITTEN. translate() takes no database session: no payment intent,",
        "  no authorization, no outbox row, no audit event, and no provider call.",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list:
        print(render_listing())
        return EXIT_OK

    if args.matrix:
        if args.json:
            print(json.dumps([e.model_dump(mode="json") for e in PROTOCOL_SUPPORT], indent=2))
        else:
            print(render_matrix())
        return EXIT_OK

    if args.limitations:
        if args.json:
            print(
                json.dumps([lim.model_dump(mode="json") for lim in ADAPTER_LIMITATIONS], indent=2)
            )
        else:
            print(render_limitations())
        return EXIT_OK

    if args.describe:
        try:
            descriptor = load_registry().describe(args.describe)
        except AdapterError as exc:
            print(f"{exc}", file=sys.stderr)
            return EXIT_FAILURE
        if args.json:
            print(json.dumps(descriptor.model_dump(mode="json"), indent=2))
        else:
            print(render_description(args.describe))
        return EXIT_OK

    if args.translate:
        if args.file is None or args.family is None or args.protocol_version is None:
            parser.error("--translate requires --file, --family and --protocol-version")
        try:
            family = AdapterFamily(args.family.upper())
        except ValueError:
            parser.error(
                f"unknown family {args.family!r}; "
                f"expected one of {', '.join(f.value for f in AdapterFamily)}"
            )
        if not args.file.is_file():
            print(f"no such fixture: {args.file}", file=sys.stderr)
            return EXIT_FAILURE

        load_registry()
        try:
            envelope = translate(
                args.translate,
                family=family,
                protocol_version=args.protocol_version,
                payload=args.file.read_bytes(),
                source=SourceIdentity(claimed_id=args.claimed_id, channel=CLI_CHANNEL),
            )
        except AdapterError as exc:
            # A refusal is the boundary working. Printed with its reason code
            # because that is the thing a developer needs, and to stderr because
            # it is not the output the command was asked for.
            print(f"REFUSED  {exc.reason_code}\n  {exc.detail}", file=sys.stderr)
            return EXIT_FAILURE

        if args.json:
            print(json.dumps(envelope.model_dump(mode="json"), indent=2, sort_keys=True))
        else:
            print(render_envelope(envelope))
        return EXIT_OK

    parser.print_help()
    return EXIT_USAGE


if __name__ == "__main__":  # pragma: no cover - exercised via main()
    raise SystemExit(main())
