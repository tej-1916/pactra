"""The adapter layer must be INCAPABLE of side effects, not merely observed to
avoid them.

Three independent proofs, modelled on ``tests/test_risk_isolation.py`` and
``tests/test_replay_isolation.py`` because the property is the same one and the
argument for proving it three ways has not changed:

1. **Structural** — every adapter module's import graph is parsed. The package
   may not import the payment executor, the authorization write path, the
   binding module, the orchestrator, or the merchant adapters. A translator that
   CAN reach an executor eventually will be asked to.
2. **Signature** — ``translate`` is synchronous and takes no session. There is
   no parameter to write through and no ``await`` to reach a provider with. This
   is the proof that generalizes to adapters nobody has written yet.
3. **Row census** — every table is counted before and after translating one
   payload through every registered adapter, with a live provider watched too.
   This catches a side effect the first two proofs did not anticipate.

The scenario under test is deliberately the fullest one available: a complete
mission with offers, a policy decision, an authorization and a payment intent
already in the database, so a translation has every opportunity to touch
something it should not.
"""

from __future__ import annotations

import ast
import pathlib

import pytest
from apps.api.db.models import (
    AuditEventRow,
    AuthorizationRow,
    Mission,
    MissionConstraintsRow,
    Offer,
    OutboxEventRow,
    PaymentIntentRow,
    PolicyDecisionRow,
    WebhookEventRow,
)
from packages.schemas.capability import payment_executor_capabilities
from packages.schemas.domain import CreateMissionRequest, MissionConstraints
from services.adapters.models import AdapterFamily, SourceIdentity
from services.adapters.translate import translate
from services.agent_orchestrator.merchants.mock_merchants import MockMerchantA
from services.agent_orchestrator.orchestrator import Orchestrator
from services.payment_executor.intents import create_payment_intent
from services.payment_executor.providers.fake import FakePaymentProvider
from services.security_kernel.authorization import (
    activate_authorization,
    authorization_for_mission,
)
from sqlalchemy import func, select

pytestmark = pytest.mark.asyncio

ADAPTERS_DIR = pathlib.Path(__file__).resolve().parents[1] / "services/adapters"

#: Module prefixes the adapter layer must not be able to reach. Each owns at
#: least one irreversible action: money movement, authorization state, a
#: transaction commitment, or a call to an untrusted merchant.
FORBIDDEN_IMPORT_PREFIXES = (
    "services.payment_executor.executor",
    "services.payment_executor.intents",
    "services.payment_executor.worker",
    "services.payment_executor.webhooks",
    "services.payment_executor.reconciliation",
    "services.payment_executor.outbox",
    "services.security_kernel.authorization",
    "services.security_kernel.binding",
    "services.agent_orchestrator",
    "services.audit_ledger",
    "services.risk_engine",
    "apps.api.db",
    "sqlalchemy",
)

#: ``payment_rails/base.py`` documents the rail boundary and therefore names the
#: PaymentProvider protocol and the provider registry. Both are import-only:
#: a Protocol class and a function returning names. Neither creates a payment,
#: and the census proof below covers what the import graph cannot.
RAIL_DOCUMENTATION_ALLOWANCE = {
    "services.payment_executor.providers.base",
    "services.payment_executor.registry",
}


def adapter_modules() -> list[pathlib.Path]:
    return sorted(ADAPTERS_DIR.rglob("*.py"))


def imported_modules(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


# --------------------------------------------------------------------------- #
# 1. Structural
# --------------------------------------------------------------------------- #
async def test_there_are_adapter_modules_to_check():
    """A sweep over an empty list passes vacuously."""
    assert len(adapter_modules()) >= 15


async def test_no_adapter_module_can_reach_a_side_effecting_component():
    offenders: list[str] = []
    for path in adapter_modules():
        relative = path.relative_to(ADAPTERS_DIR)
        for module in imported_modules(path):
            if module in RAIL_DOCUMENTATION_ALLOWANCE and relative.parts[0] == "payment_rails":
                continue
            for forbidden in FORBIDDEN_IMPORT_PREFIXES:
                if module == forbidden or module.startswith(f"{forbidden}."):
                    offenders.append(f"{relative}: {module}")
    assert not offenders, f"adapter modules can reach side-effecting components: {offenders}"


async def test_the_rail_allowance_is_confined_to_the_module_that_documents_it():
    """The one exception must not become a general one."""
    for path in adapter_modules():
        relative = path.relative_to(ADAPTERS_DIR)
        if relative.parts[0] == "payment_rails":
            continue
        assert not (imported_modules(path) & RAIL_DOCUMENTATION_ALLOWANCE), relative


async def test_no_adapter_module_imports_an_llm_client():
    """Security translation is deterministic Python, never a prompt."""
    forbidden = {"openai", "anthropic", "langchain", "llama_index", "transformers", "litellm"}
    for path in adapter_modules():
        assert not ({m.split(".")[0] for m in imported_modules(path)} & forbidden), (
            f"{path.name} imports an LLM client"
        )


# --------------------------------------------------------------------------- #
# 2. Signature
# --------------------------------------------------------------------------- #
async def test_no_public_adapter_entry_point_is_async_or_takes_a_session():
    """The proof that generalizes to adapters nobody has written yet."""
    import inspect

    from services.adapters.registry import load_registry

    session_names = {"session", "sessionmaker", "db", "engine", "connection", "conn"}

    assert not inspect.iscoroutinefunction(translate)
    assert not (set(inspect.signature(translate).parameters) & session_names)

    for descriptor in load_registry().list():
        implementation = (
            load_registry().get(descriptor.adapter_id, family=descriptor.family).implementation
        )
        method = implementation.translate_payload
        assert not inspect.iscoroutinefunction(method), descriptor.adapter_id
        assert not (set(inspect.signature(method).parameters) & session_names)


# --------------------------------------------------------------------------- #
# 3. Row census, against a database with something to disturb
# --------------------------------------------------------------------------- #
TABLES = (
    Mission,
    MissionConstraintsRow,
    Offer,
    PolicyDecisionRow,
    AuthorizationRow,
    PaymentIntentRow,
    OutboxEventRow,
    WebhookEventRow,
    AuditEventRow,
)

FIXTURES = (
    (
        "mcp.tools-call.v1",
        AdapterFamily.TOOL,
        "2025-06-18",
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "pactra.purchase.propose", "arguments": {"quantity": 1}},
        },
    ),
    (
        "pactra.commerce.v1",
        AdapterFamily.COMMERCE,
        "1.0",
        {
            "protocol": "pactra.commerce",
            "merchant_id": "merchant_a",
            "offers": [
                {
                    "merchant_id": "merchant_a",
                    "product_id": "aur-eb-01",
                    "title": "Aurora Earbuds",
                    "description": "x",
                    "price": 4299,
                    "currency": "INR",
                    "rating": 4.6,
                    "in_stock": True,
                    "offered_at": "2026-01-01T12:00:00+00:00",
                }
            ],
        },
    ),
    (
        "pactra.authorization-intent.v1",
        AdapterFamily.PAYMENT_AUTHORIZATION,
        "1.0",
        {
            "protocol": "pactra.authorization-intent",
            "merchant_id": "merchant_a",
            "product_id": "P1",
            "quantity": 1,
            "amount_inr": 3799,
            "currency": "INR",
            "expires_at": "2030-01-01T12:00:00+00:00",
        },
    ),
)


async def census(session) -> dict[str, int]:
    counts = {}
    for model in TABLES:
        result = await session.execute(select(func.count()).select_from(model))
        counts[model.__tablename__] = int(result.scalar_one())
    return counts


async def protected_state(session) -> dict[str, list[tuple]]:
    """Values translation must not mutate, beyond merely keeping row counts."""
    constraints = (
        await session.execute(select(MissionConstraintsRow).order_by(MissionConstraintsRow.id))
    ).scalars()
    decisions = (
        await session.execute(select(PolicyDecisionRow).order_by(PolicyDecisionRow.id))
    ).scalars()
    authorizations = (
        await session.execute(select(AuthorizationRow).order_by(AuthorizationRow.authorization_id))
    ).scalars()
    return {
        "policy": [
            (
                row.id,
                row.soft_budget_inr,
                row.hard_limit_inr,
                row.currency,
                row.min_rating,
                tuple(row.allowed_merchants or ()),
                tuple(row.blocked_merchants or ()),
                row.min_merchant_trust,
            )
            for row in constraints
        ],
        "decisions": [
            (
                row.id,
                row.decision,
                row.policy_version,
                tuple(row.reason_codes),
                row.requested_amount,
                row.soft_budget,
                row.hard_limit,
                row.selected_offer_id,
            )
            for row in decisions
        ],
        "authorizations": [
            (
                row.authorization_id,
                row.status,
                row.consumed_at,
                row.transaction_digest,
                row.bound_merchant_id,
                row.bound_product_id,
                row.bound_quantity,
                row.bound_amount_inr,
                row.bound_currency,
            )
            for row in authorizations
        ],
    }


async def test_translation_creates_no_row_and_calls_no_provider(session):
    """The fullest available scenario: a mission with a live payment intent."""
    mission = await Orchestrator(merchants=[MockMerchantA()]).run(
        session,
        CreateMissionRequest(
            raw_query="earbuds",
            quantity=1,
            constraints=MissionConstraints(
                category="wireless_earbuds",
                soft_budget_inr=4000,
                hard_limit_inr=4500,
                min_rating=4.2,
            ),
        ),
    )
    authorization = await authorization_for_mission(session, mission.id)
    assert authorization is not None
    await activate_authorization(session, authorization_id=authorization.authorization_id)
    mission.state = "AUTHORIZED"
    await session.flush()
    await create_payment_intent(
        session,
        capabilities=payment_executor_capabilities(),
        mission_id=mission.id,
        authorization_id=authorization.authorization_id,
        idempotency_key="isolation-key",
        provider="fake",
    )
    await session.flush()

    provider = FakePaymentProvider()
    before = await census(session)
    protected_before = await protected_state(session)
    provider_payments_before = len(provider.created_payments)

    for adapter_id, family, version, payload in FIXTURES:
        envelope = translate(
            adapter_id,
            family=family,
            protocol_version=version,
            payload=payload,
            source=SourceIdentity(claimed_id="isolation-caller", channel="pytest"),
        )
        assert envelope.taint is True

    await session.flush()
    after = await census(session)
    protected_after = await protected_state(session)

    assert after == before, f"translation changed rows: {before} -> {after}"
    assert protected_after == protected_before, "translation mutated policy or authorization state"
    assert len(provider.created_payments) == provider_payments_before
    # And named explicitly, because these are the four the phase promises.
    assert after["payment_intents"] == before["payment_intents"]
    assert after["authorizations"] == before["authorizations"]
    assert after["outbox_events"] == before["outbox_events"]
    assert after["audit_events"] == before["audit_events"]


async def test_translation_does_not_consume_an_authorization(session):
    """An ACTIVE authorization is still ACTIVE afterwards, and still spendable."""
    from packages.schemas.authorization import AuthorizationStatus

    mission = await Orchestrator(merchants=[MockMerchantA()]).run(
        session,
        CreateMissionRequest(
            raw_query="earbuds",
            quantity=1,
            constraints=MissionConstraints(
                category="wireless_earbuds",
                soft_budget_inr=4000,
                hard_limit_inr=4500,
                min_rating=4.2,
            ),
        ),
    )
    authorization = await authorization_for_mission(session, mission.id)
    assert authorization is not None
    await activate_authorization(session, authorization_id=authorization.authorization_id)
    await session.flush()

    for adapter_id, family, version, payload in FIXTURES:
        translate(
            adapter_id,
            family=family,
            protocol_version=version,
            payload=payload,
            source=SourceIdentity(claimed_id="isolation-caller", channel="pytest"),
        )

    await session.refresh(authorization)
    assert authorization.status == AuthorizationStatus.ACTIVE.value
    assert authorization.consumed_at is None


async def test_replay_never_invokes_an_adapter():
    """Deterministic replay must never reach an external system.

    Phase 5 proved the reducer imports nothing that performs I/O. Phase 8 adds a
    package that TRANSLATES external protocol data, so the same guarantee has to
    be restated for it: a replay that called an adapter would be a replay whose
    output depended on a payload nobody kept.
    """
    replay_module = pathlib.Path(__file__).resolve().parents[1] / "services/audit_ledger/replay.py"
    imports = imported_modules(replay_module)
    assert not any(
        module == "services.adapters" or module.startswith("services.adapters.")
        for module in imports
    ), "the replay reducer can reach the adapter layer"


async def test_no_kernel_component_imports_the_adapter_layer():
    """Adapters depend on the kernel. The kernel must not depend on adapters.

    A one-way dependency is what keeps an adapter substitutable and keeps the
    security kernel's behaviour independent of which protocols happen to be
    registered.
    """
    root = pathlib.Path(__file__).resolve().parents[1]
    offenders: list[str] = []
    for area in ("services/security_kernel", "services/policy_engine", "services/payment_executor"):
        for path in sorted((root / area).rglob("*.py")):
            if any(
                module == "services.adapters" or module.startswith("services.adapters.")
                for module in imported_modules(path)
            ):
                offenders.append(str(path.relative_to(root)))
    assert not offenders, f"kernel components import the adapter layer: {offenders}"
