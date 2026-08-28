"""Protocol claims must be no broader than the code that exists."""

from __future__ import annotations

import pathlib

from services.adapters.models import AdapterFamily, SupportStatus
from services.adapters.payment_rails import RAIL_STATUS
from services.adapters.registry import load_registry
from services.adapters.support import PROTOCOL_SUPPORT

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS = (ROOT / "README.md", ROOT / "docs/architecture.md")


def test_protocol_support_matrix_has_one_row_per_protocol():
    protocols = [entry.protocol for entry in PROTOCOL_SUPPORT]
    assert len(protocols) == len(set(protocols))
    assert {"Razorpay", "MCP", "ACP", "AP2", "x402"} <= set(protocols)


def test_support_matrix_matches_the_registered_translation_adapters():
    registry = load_registry()
    claimed_adapter_ids: set[str] = set()

    for entry in PROTOCOL_SUPPORT:
        if entry.adapter_id is None:
            continue
        assert entry.status in {SupportStatus.IMPLEMENTED, SupportStatus.PARTIAL}
        assert entry.family is not None
        descriptor = registry.get(entry.adapter_id, family=entry.family).descriptor
        assert descriptor.status is entry.status
        claimed_adapter_ids.add(entry.adapter_id)

    assert claimed_adapter_ids == set(registry.ids())


def test_planned_protocols_have_no_adapter_to_resolve():
    registry = load_registry()
    registered_protocols = {descriptor.protocol_name for descriptor in registry.list()}
    for entry in PROTOCOL_SUPPORT:
        if entry.status is not SupportStatus.PLANNED:
            continue
        assert entry.adapter_id is None
        assert entry.protocol not in registered_protocols


def test_razorpay_row_matches_the_existing_payment_rail_registry():
    row = next(entry for entry in PROTOCOL_SUPPORT if entry.protocol == "Razorpay")
    assert row.family is AdapterFamily.PAYMENT_RAIL
    assert row.status is RAIL_STATUS["razorpay_test"] is SupportStatus.PARTIAL
    assert row.adapter_id is None, "payment rails do not belong in the translation registry"


def test_named_external_protocols_are_classified_honestly():
    rows = {entry.protocol: entry for entry in PROTOCOL_SUPPORT}
    assert rows["MCP"].family is AdapterFamily.TOOL
    assert rows["MCP"].status is SupportStatus.PARTIAL
    assert rows["AP2"].family is AdapterFamily.PAYMENT_AUTHORIZATION
    assert rows["AP2"].status is SupportStatus.PLANNED
    assert rows["ACP"].status is SupportStatus.PLANNED
    assert rows["x402"].status is SupportStatus.PLANNED


def test_readme_and_architecture_tables_match_the_machine_matrix():
    """Every machine row appears once in each authoritative human document."""
    for path in DOCS:
        text = path.read_text()
        for entry in PROTOCOL_SUPPORT:
            lines = [
                line for line in text.splitlines() if line.startswith(f"| `{entry.protocol}` |")
            ]
            assert len(lines) == 1, f"{path.name}: expected one row for {entry.protocol}"
            family = entry.family.display_name if entry.family else "(unassigned)"
            assert f"| `{family}` |" in lines[0]
            assert lines[0].endswith(f"| `{entry.status.value}` |")
