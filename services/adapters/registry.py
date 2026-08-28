"""Server-owned adapter registry.

ADAPTER IDENTITY IS SERVER-OWNED, AND THAT IS THE WHOLE POINT
-------------------------------------------------------------
A caller must not be able to say ``adapter_id = "trusted_mcp_adapter"`` and
acquire anything. Three things enforce that together:

1. **Registration is a function call in source, not discovery.** There is no
   filesystem scan, no entry-point scan, and — checked by
   ``tests/test_adapter_registry.py`` — no ``importlib``, ``__import__`` or
   ``eval`` anywhere in this module. A caller cannot name a class path and have
   it loaded. The set of adapters PACTRA has is the set written down here and
   in ``services/adapters/__init__.py``.
2. **Resolution requires the caller to state the family it expects.**
   ``get(adapter_id, family=...)`` refuses a match in a different family. A
   ``ToolAdapter`` resolved as a ``CommerceAdapter`` would translate a tool call
   into commerce semantics and call the result canonical.
3. **The descriptor, not the payload, is the adapter's identity.** ``translate``
   copies adapter id, protocol name, protocol version and adapter version out of
   the registered ``AdapterDescriptor``. A payload key named ``adapter_id`` is a
   reserved field and is rejected outright.

WHAT REGISTRATION REFUSES, AND WHY EACH ONE
-------------------------------------------
* a duplicate id — a silently overwritten adapter means one protocol boundary
  stopped being the one the support matrix names, while the matrix keeps saying
  it is there (the same argument the attack-lab scenario registry makes);
* ``PAYMENT_RAIL`` — a rail EXECUTES; its boundary is the Phase 4
  ``PaymentProvider`` protocol resolved through
  ``services.payment_executor.registry``, and putting an execution adapter in a
  registry of pure translations is exactly the cross-family confusion this phase
  corrects;
* ``AGENT_COMMUNICATION`` — declared as a family so the support matrix can type
  ACP's row, deliberately holding no implementation;
* an implementation that is not an instance of its family's base class;
* a descriptor whose ``emits_authority`` exceeds ``AGENT_PROPOSAL``, or whose
  ``emits_trust`` is anything but untrusted.

WHAT THE REGISTRY DELIBERATELY HAS NO API FOR
---------------------------------------------
Deregistering, re-registering, mutating a descriptor (they are frozen), or
changing an adapter's trust at runtime. There is no HTTP route into this module
and no CLI flag that registers anything; ``services/adapters/run.py`` reads.
"""

from __future__ import annotations

from typing import cast

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
)
from services.adapters.tools.base import ToolAdapter

AdapterImplementation = CommerceAdapter | PaymentAuthorizationAdapter | ToolAdapter

#: Module-level aliases so annotations below mean the BUILTIN types rather than
#: the methods that shadow them inside the class body. Same reason the attack
#: lab's scenario registry does it.
DescriptorList = list[AdapterDescriptor]
IdList = list[str]

#: The base class each translating family requires. An implementation that is
#: not an instance of its family's base is refused: the family is what decides
#: which canonical payload type the envelope may carry, so a mismatch there
#: would make the payload-type check meaningless.
FAMILY_BASE_CLASSES: dict[AdapterFamily, type] = {
    AdapterFamily.COMMERCE: CommerceAdapter,
    AdapterFamily.PAYMENT_AUTHORIZATION: PaymentAuthorizationAdapter,
    AdapterFamily.TOOL: ToolAdapter,
}

#: Why a family holds no translating adapter. Surfaced verbatim in the refusal
#: so a developer who tries gets the reason rather than a bare "no".
NON_TRANSLATING_FAMILY_REASONS: dict[AdapterFamily, str] = {
    AdapterFamily.PAYMENT_RAIL: (
        "a payment rail EXECUTES rather than translates; its boundary is the "
        "PaymentProvider protocol, resolved through "
        "services.payment_executor.registry and reachable only from the payment "
        "executor under the payment.execute capability"
    ),
    AdapterFamily.AGENT_COMMUNICATION: (
        "the agent-communication family is declared but not implemented: no "
        "protocol requirement in this repository justifies one, and an empty "
        "base class is decoration (see services/adapters/agents/__init__.py)"
    ),
}


class RegisteredAdapter:
    """A descriptor and its implementation, resolved together. Immutable.

    The implementation is reachable only through a registry lookup that named a
    family, so there is no way to hold an implementation without having stated
    what you believed it was.

    IMMUTABLE BECAUSE ``get`` HANDS OUT THE LIVE ENTRY. This object IS the
    registry's record, not a copy of it, so ordinary attribute assignment on a
    resolved adapter would re-label the registry for every subsequent caller —
    ``registered.descriptor = something_else`` and the process now believes an
    adapter is something it is not. ``AdapterDescriptor`` being a frozen model
    does not help: the binding between id and descriptor is what would move.
    ``__setattr__`` therefore refuses everything after construction, which the
    ``adapter_registry_bypass`` scenario measures.

    Found by that scenario during Phase 8 construction rather than reasoned about
    in advance, which is the argument for the scenario existing.
    """

    __slots__ = ("descriptor", "implementation")

    descriptor: AdapterDescriptor
    implementation: AdapterImplementation

    def __init__(
        self, descriptor: AdapterDescriptor, implementation: AdapterImplementation
    ) -> None:
        object.__setattr__(self, "descriptor", descriptor)
        object.__setattr__(self, "implementation", implementation)

    def __setattr__(self, name: str, value: object) -> None:
        raise AdapterRegistrationRefused(
            f"a registered adapter is immutable; refusing to reassign {name!r}. "
            "This object is the registry's own record, so reassigning it would "
            "re-label the adapter for every subsequent caller."
        )

    def __delattr__(self, name: str) -> None:
        raise AdapterRegistrationRefused(
            f"a registered adapter is immutable; refusing to delete {name!r}"
        )

    @property
    def adapter_id(self) -> str:
        return self.descriptor.adapter_id

    @property
    def family(self) -> AdapterFamily:
        return self.descriptor.family


class AdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, RegisteredAdapter] = {}
        self._sealed = False

    # ------------------------------------------------------------------ #
    # Registration — import-time only
    # ------------------------------------------------------------------ #
    def register(self, descriptor: AdapterDescriptor, implementation: object) -> RegisteredAdapter:
        if self._sealed:
            raise AdapterRegistrationRefused(
                "the server-owned adapter registry is sealed; runtime or "
                "caller-supplied registration is not permitted"
            )
        if descriptor.adapter_id in self._adapters:
            raise DuplicateAdapter(f"adapter id {descriptor.adapter_id!r} is already registered")

        if descriptor.family not in TRANSLATING_FAMILIES:
            reason = NON_TRANSLATING_FAMILY_REASONS.get(
                descriptor.family, "family holds no translating adapter"
            )
            raise AdapterRegistrationRefused(
                f"{descriptor.family.display_name} may not be registered here: {reason}"
            )

        base = FAMILY_BASE_CLASSES[descriptor.family]
        if not isinstance(implementation, base):
            raise AdapterRegistrationRefused(
                f"adapter {descriptor.adapter_id!r} declares family "
                f"{descriptor.family.display_name} but its implementation is a "
                f"{type(implementation).__name__}, not a {base.__name__}"
            )

        declared_family = getattr(implementation, "family", None)
        if declared_family is not descriptor.family:
            raise AdapterRegistrationRefused(
                f"adapter {descriptor.adapter_id!r} is registered as "
                f"{descriptor.family.value} but reports family {declared_family}"
            )

        # Re-checked here even though AdapterDescriptor validates it: the
        # ceiling is a security property, and a security property enforced in
        # exactly one place is one refactor away from being enforced in none.
        if descriptor.emits_authority > MAX_ADAPTER_AUTHORITY:
            raise AdapterRegistrationRefused(
                f"adapter {descriptor.adapter_id!r} would emit "
                f"{descriptor.emits_authority.name}, above the adapter ceiling "
                f"{MAX_ADAPTER_AUTHORITY.name}"
            )

        # The family-specific ``isinstance`` check above narrows this at runtime;
        # spelling out the three alternatives here keeps every later registry
        # consumer typed to a translating adapter rather than arbitrary object.
        registered = RegisteredAdapter(descriptor, cast(AdapterImplementation, implementation))
        self._adapters[descriptor.adapter_id] = registered
        return registered

    def seal(self) -> None:
        """Permanently close this registry to further registration.

        The process-wide registry is sealed immediately after the explicit
        built-in adapter list is registered. Private registries used while
        validating registration rules remain mutable until their owner seals
        them, but a caller cannot add an implementation to the registry used by
        :func:`services.adapters.translate`.
        """
        self._sealed = True

    @property
    def sealed(self) -> bool:
        return self._sealed

    # ------------------------------------------------------------------ #
    # Resolution — the family is an argument, never an inference
    # ------------------------------------------------------------------ #
    def get(self, adapter_id: str, *, family: AdapterFamily) -> RegisteredAdapter:
        """Resolve an adapter, requiring the caller to state its family.

        ``family`` is keyword-only and has no default. A default would be a
        choice the caller did not make, and cross-family confusion is precisely
        a caller acting on an adapter it did not think it had.
        """
        registered = self._adapters.get(adapter_id)
        if registered is None:
            raise UnknownAdapter(adapter_id)
        if registered.family is not family:
            raise AdapterFamilyMismatch(
                adapter_id,
                expected=family.display_name,
                actual=registered.family.display_name,
            )
        return registered

    def describe(self, adapter_id: str) -> AdapterDescriptor:
        """The public description of an adapter, with no implementation attached.

        Family-agnostic on purpose: describing is not acting, and a listing that
        refused to name an adapter unless you already knew its family would be
        useless for the one thing a listing is for.
        """
        registered = self._adapters.get(adapter_id)
        if registered is None:
            raise UnknownAdapter(adapter_id)
        return registered.descriptor

    def has(self, adapter_id: str) -> bool:
        return adapter_id in self._adapters

    def list(self, *, family: AdapterFamily | None = None) -> DescriptorList:
        """Registered descriptors in registration order, optionally filtered."""
        descriptors: DescriptorList = [r.descriptor for r in self._adapters.values()]
        if family is not None:
            descriptors = [d for d in descriptors if d.family is family]
        return descriptors

    def ids(self) -> IdList:
        return list(self._adapters)

    def __len__(self) -> int:
        return len(self._adapters)


#: The process-wide registry. Populated by importing ``services.adapters``,
#: which is the only module that registers.
REGISTRY = AdapterRegistry()


def register(descriptor: AdapterDescriptor, implementation: object) -> RegisteredAdapter:
    return REGISTRY.register(descriptor, implementation)


def load_registry() -> AdapterRegistry:
    """Import the adapter package (idempotent) and return the registry."""
    import services.adapters  # noqa: F401  (registration side effect)

    return REGISTRY
