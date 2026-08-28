"""Registry integrity: adapter identity is server-owned, or it is nothing.

The failure this file exists to prevent is a caller acquiring trust by naming
it. Every test here is one route to that: registering, re-labelling,
substituting a family, resolving an unknown id, or reaching an implementation
through a string somebody supplied.

Modelled on ``tests/test_attack_lab_registry.py``, whose argument transfers
directly — a registry whose contents depend on what happened to import is a
registry whose claims cannot be checked.
"""

from __future__ import annotations

import ast
import pathlib

import pytest
from packages.schemas.provenance import AuthorityLevel
from services.adapters.agents import NOT_IMPLEMENTED_REASON
from services.adapters.authorization.base import PaymentAuthorizationAdapter
from services.adapters.commerce.base import CommerceAdapter
from services.adapters.errors import (
    AdapterFamilyMismatch,
    AdapterRegistrationRefused,
    DuplicateAdapter,
    UnknownAdapter,
)
from services.adapters.models import (
    MAX_ADAPTER_AUTHORITY,
    TRANSLATING_FAMILIES,
    AdapterDescriptor,
    AdapterFamily,
    SupportStatus,
)
from services.adapters.registry import (
    FAMILY_BASE_CLASSES,
    REGISTRY,
    AdapterRegistry,
    load_registry,
)
from services.adapters.tools.base import ToolAdapter
from services.adapters.translate import translate

ADAPTERS_DIR = pathlib.Path(__file__).resolve().parents[1] / "services/adapters"

MCP = "mcp.tools-call.v1"
COMMERCE = "pactra.commerce.v1"
INTENT = "pactra.authorization-intent.v1"


def descriptor(**overrides) -> AdapterDescriptor:
    base = dict(
        adapter_id="test.adapter.v1",
        family=AdapterFamily.TOOL,
        protocol_name="test",
        protocol_version="1.0",
        supported_protocol_versions=("1.0",),
        adapter_version="test-1",
        status=SupportStatus.IMPLEMENTED,
        summary="A descriptor used only by the adapter registry tests.",
    )
    base.update(overrides)
    return AdapterDescriptor(**base)


class StubTool(ToolAdapter):
    descriptor = descriptor()

    def translate_payload(self, payload, *, source, protocol_version):  # noqa: ANN001
        raise NotImplementedError


class StubCommerce(CommerceAdapter):
    descriptor = descriptor(family=AdapterFamily.COMMERCE)

    def translate_payload(self, payload, *, source, protocol_version):  # noqa: ANN001
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# What is registered
# --------------------------------------------------------------------------- #
def test_the_three_declared_adapters_are_registered():
    registry = load_registry()
    for adapter_id in (MCP, COMMERCE, INTENT):
        assert registry.has(adapter_id), f"{adapter_id} is not registered"


def test_every_registered_adapter_is_in_a_translating_family():
    for descriptor_ in load_registry().list():
        assert descriptor_.family in TRANSLATING_FAMILIES


def test_the_agent_family_holds_no_adapter():
    """Declared so the support matrix can type ACP's row; implemented nowhere."""
    assert not load_registry().list(family=AdapterFamily.AGENT_COMMUNICATION)
    assert AdapterFamily.AGENT_COMMUNICATION not in FAMILY_BASE_CLASSES
    assert NOT_IMPLEMENTED_REASON


def test_the_payment_rail_family_holds_no_translating_adapter():
    """A rail EXECUTES. It does not belong in a registry of pure functions."""
    assert not load_registry().list(family=AdapterFamily.PAYMENT_RAIL)
    assert AdapterFamily.PAYMENT_RAIL not in FAMILY_BASE_CLASSES


def test_every_adapter_id_is_unique():
    ids = load_registry().ids()
    assert len(ids) == len(set(ids))


def test_no_registered_adapter_may_emit_above_the_ceiling():
    for descriptor_ in load_registry().list():
        assert descriptor_.emits_authority <= MAX_ADAPTER_AUTHORITY
        assert descriptor_.emits_authority <= AuthorityLevel.AGENT_PROPOSAL


def test_the_registry_import_is_idempotent():
    """A module imported twice must not raise DuplicateAdapter."""
    import importlib

    import services.adapters as adapters_module

    before = len(REGISTRY)
    importlib.reload(adapters_module)
    assert len(REGISTRY) == before


def test_the_process_registry_is_sealed_against_caller_registration():
    """The public translation path cannot be extended at runtime.

    Private registries remain useful for testing registration invariants, but
    the process registry used by ``translate`` is closed after bootstrap.
    """
    assert REGISTRY.sealed is True
    with pytest.raises(AdapterRegistrationRefused):
        REGISTRY.register(
            descriptor(adapter_id="caller.supplied.v1"),
            StubTool(),
        )
    assert not REGISTRY.has("caller.supplied.v1")


def test_translate_cannot_be_given_a_caller_owned_registry():
    """A registry parameter would let the caller choose the implementation."""
    import inspect

    assert "registry" not in inspect.signature(translate).parameters


# --------------------------------------------------------------------------- #
# Resolution
# --------------------------------------------------------------------------- #
def test_an_unknown_adapter_is_refused_and_never_defaulted():
    registry = load_registry()
    for name in ("trusted_mcp_adapter", "", "mcp.tools-call.v2"):
        with pytest.raises(UnknownAdapter):
            registry.get(name, family=AdapterFamily.TOOL)


def test_a_class_path_is_not_an_adapter_id():
    """The shape a dynamic-import bypass would take."""
    with pytest.raises(UnknownAdapter):
        load_registry().get("services.adapters.tools.mcp.McpToolAdapter", family=AdapterFamily.TOOL)


@pytest.mark.parametrize(
    ("adapter_id", "wrong_family"),
    [
        (MCP, AdapterFamily.COMMERCE),
        (MCP, AdapterFamily.PAYMENT_AUTHORIZATION),
        (COMMERCE, AdapterFamily.TOOL),
        (COMMERCE, AdapterFamily.PAYMENT_RAIL),
        (INTENT, AdapterFamily.TOOL),
        (INTENT, AdapterFamily.AGENT_COMMUNICATION),
    ],
)
def test_resolving_under_the_wrong_family_is_refused(adapter_id, wrong_family):
    with pytest.raises(AdapterFamilyMismatch):
        load_registry().get(adapter_id, family=wrong_family)


def test_the_family_argument_has_no_default():
    """A default would be a choice the caller did not make, and cross-family
    confusion is precisely a caller acting on an adapter it did not think it
    had."""
    import inspect

    signature = inspect.signature(AdapterRegistry.get)
    family = signature.parameters["family"]
    assert family.kind is inspect.Parameter.KEYWORD_ONLY
    assert family.default is inspect.Parameter.empty


def test_describe_is_family_agnostic_because_describing_is_not_acting():
    assert load_registry().describe(MCP).adapter_id == MCP
    with pytest.raises(UnknownAdapter):
        load_registry().describe("no-such-adapter")


# --------------------------------------------------------------------------- #
# Registration refusals
# --------------------------------------------------------------------------- #
def test_a_duplicate_id_is_refused():
    registry = AdapterRegistry()
    registry.register(descriptor(), StubTool())
    with pytest.raises(DuplicateAdapter):
        registry.register(descriptor(), StubTool())


def test_a_payment_rail_cannot_be_registered_as_a_translating_adapter():
    registry = AdapterRegistry()
    with pytest.raises(AdapterRegistrationRefused) as exc:
        registry.register(descriptor(family=AdapterFamily.PAYMENT_RAIL), StubTool())
    assert "EXECUTES" in str(exc.value) or "execut" in str(exc.value).lower()


def test_the_agent_family_cannot_be_registered_into():
    registry = AdapterRegistry()
    with pytest.raises(AdapterRegistrationRefused):
        registry.register(descriptor(family=AdapterFamily.AGENT_COMMUNICATION), StubTool())


def test_an_implementation_of_the_wrong_base_class_is_refused():
    registry = AdapterRegistry()
    with pytest.raises(AdapterRegistrationRefused):
        registry.register(descriptor(family=AdapterFamily.COMMERCE), StubTool())
    with pytest.raises(AdapterRegistrationRefused):
        registry.register(descriptor(family=AdapterFamily.TOOL), StubCommerce())


def test_an_implementation_that_is_not_an_adapter_at_all_is_refused():
    registry = AdapterRegistry()
    with pytest.raises(AdapterRegistrationRefused):
        registry.register(descriptor(), object())


def test_every_translating_family_declares_a_base_class():
    assert set(FAMILY_BASE_CLASSES) == set(TRANSLATING_FAMILIES)
    assert FAMILY_BASE_CLASSES[AdapterFamily.TOOL] is ToolAdapter
    assert FAMILY_BASE_CLASSES[AdapterFamily.COMMERCE] is CommerceAdapter
    assert FAMILY_BASE_CLASSES[AdapterFamily.PAYMENT_AUTHORIZATION] is PaymentAuthorizationAdapter


# --------------------------------------------------------------------------- #
# Immutability — the registry hands out its LIVE entry
# --------------------------------------------------------------------------- #
def test_a_registered_entry_cannot_be_relabelled():
    """``get`` returns the registry's own record, not a copy.

    Reassigning its descriptor would re-label the adapter for every subsequent
    caller. Found by the adapter_registry_bypass attack-lab scenario during
    construction, which is the argument for that scenario existing.
    """
    registered = load_registry().get(MCP, family=AdapterFamily.TOOL)
    with pytest.raises(AdapterRegistrationRefused):
        registered.descriptor = descriptor(adapter_id="hostile")
    with pytest.raises(AdapterRegistrationRefused):
        registered.implementation = StubTool()
    with pytest.raises(AdapterRegistrationRefused):
        del registered.descriptor
    assert load_registry().describe(MCP).adapter_id == MCP


# --------------------------------------------------------------------------- #
# No dynamic loading, anywhere in the package
# --------------------------------------------------------------------------- #
#: Names that would let a caller-supplied string become executable code. A
#: registry that could import by name is a registry whose contents an attacker
#: chooses.
FORBIDDEN_DYNAMIC_NAMES = frozenset(
    {"importlib", "__import__", "eval", "exec", "compile", "pkgutil", "entry_points"}
)


def adapter_modules() -> list[pathlib.Path]:
    return sorted(ADAPTERS_DIR.rglob("*.py"))


def test_there_are_adapter_modules_to_check():
    """A sweep over an empty list passes vacuously."""
    assert len(adapter_modules()) >= 15


def test_no_adapter_module_can_load_code_by_name():
    offenders: list[str] = []
    for path in adapter_modules():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in FORBIDDEN_DYNAMIC_NAMES:
                        offenders.append(f"{path.name}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".")[0] in FORBIDDEN_DYNAMIC_NAMES:
                    offenders.append(f"{path.name}: from {node.module}")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in FORBIDDEN_DYNAMIC_NAMES:
                    offenders.append(f"{path.name}: {node.func.id}()")
    assert not offenders, f"adapter modules can load code by name: {offenders}"


def test_the_registry_module_exposes_no_deregistration_or_mutation_api():
    """Nothing removes, replaces, or re-trusts an adapter at runtime."""
    forbidden = {"unregister", "deregister", "remove", "replace", "set_trust", "clear", "update"}
    exposed = {name for name in dir(AdapterRegistry) if not name.startswith("_")}
    assert not (exposed & forbidden), f"registry exposes mutation API: {exposed & forbidden}"
