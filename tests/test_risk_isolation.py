"""The risk engine must be INCAPABLE of side effects, not merely observed to
avoid them.

Three independent proofs, modelled on ``tests/test_replay_isolation.py`` because
the property is the same one and the argument for proving it three ways has not
changed:

1. **Structural** — every risk module's import graph is parsed. The core may not
   import the payment executor, the authorization write path, the merchant
   adapters, or the orchestrator. A scorer that CAN reach an executor eventually
   will be asked to.
2. **Landmines** — every function that could move money, mint or spend an
   authorization, or call a merchant is replaced with one that raises. If the
   engine touched any of them the failure names what it touched.
3. **Row census** — every table is counted before and after. This catches a side
   effect the first two proofs did not anticipate.

The mission under test carries a full history — offers, a policy decision, an
authorization, a payment intent, an outbox event, a provider call — so the
assessment has every opportunity to do something it should not.
"""

from __future__ import annotations

import ast
import pathlib
import uuid

import pytest
from apps.api.db.models import (
    AuditEventRow,
    AuthorizationRow,
    Mission,
    OutboxEventRow,
    PaymentIntentRow,
    WebhookEventRow,
)
from packages.schemas.capability import payment_executor_capabilities
from packages.schemas.domain import CreateMissionRequest, MissionConstraints
from packages.schemas.payment import OutboxStatus
from services.agent_orchestrator.merchants.mock_merchants import MockMerchantA
from services.agent_orchestrator.orchestrator import Orchestrator
from services.payment_executor.intents import create_payment_intent
from services.payment_executor.providers.fake import FakePaymentProvider
from services.risk_engine.engine import assess_mission
from services.security_kernel.authorization import (
    activate_authorization,
    authorization_for_mission,
)
from sqlalchemy import func, select

pytestmark = pytest.mark.asyncio

RISK_DIR = pathlib.Path(__file__).resolve().parents[1] / "services/risk_engine"

#: Modules that must be reachable from a request path. Deliberately excludes
#: ``scenarios.py``, ``evaluation.py``, ``report.py`` and ``run.py``: those are
#: the evaluation harness, which BUILDS missions and therefore must be able to
#: call the kernel — the same reason the attack lab may.
CORE_MODULES = (
    "__init__.py",
    "models.py",
    "config.py",
    "features.py",
    "anomaly.py",
    "heuristic.py",
    "explain.py",
    "engine.py",
)

#: Module prefixes the scorer must not be able to reach. Each owns at least one
#: irreversible action: money movement, authorization state, or a call to an
#: untrusted merchant.
FORBIDDEN_IMPORT_PREFIXES = (
    "services.payment_executor",
    "services.security_kernel.authorization",
    "services.security_kernel.binding",
    "services.security_kernel.capability",
    "services.agent_orchestrator",
    "services.attack_lab",
)

_COUNTED_TABLES = {
    "missions": Mission,
    "audit_events": AuditEventRow,
    "authorizations": AuthorizationRow,
    "payment_intents": PaymentIntentRow,
    "outbox_events": OutboxEventRow,
    "webhook_events": WebhookEventRow,
}

EXECUTOR = payment_executor_capabilities()


def _imports(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
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
@pytest.mark.parametrize("module_name", CORE_MODULES)
async def test_the_risk_core_cannot_import_a_side_effecting_module(module_name):
    path = RISK_DIR / module_name
    offenders = sorted(
        name
        for name in _imports(path)
        for prefix in FORBIDDEN_IMPORT_PREFIXES
        if name == prefix or name.startswith(prefix + ".")
    )
    assert offenders == [], f"{module_name} imports {offenders}"


async def test_the_risk_core_may_read_the_merchant_registry():
    """The one security-kernel module it IS allowed: a read-only trust table.

    Stated as a positive assertion so the allowance is deliberate rather than an
    accident of how the deny-list was spelled.
    """
    assert "services.security_kernel.merchant_registry" in _imports(RISK_DIR / "features.py")


async def test_the_only_ledger_write_lives_in_record_assessment():
    """``append_event`` may be imported by ``engine.py`` and nowhere else.

    ``record_assessment`` is the engine's single write. If ``features.py`` or
    ``heuristic.py`` could append an event, "assessment is read-only" would stop
    being true the first time somebody added a diagnostic.
    """
    for module_name in CORE_MODULES:
        names = _imports(RISK_DIR / module_name)
        writes = {n for n in names if n == "services.audit_ledger.ledger"}
        if module_name == "engine.py":
            assert writes, "engine.py should own the ledger import"
        elif module_name == "features.py":
            # features.py imports the ledger for `list_events` (a read). Assert
            # it does not import the append path by name.
            source = (RISK_DIR / module_name).read_text()
            assert "append_event" not in source, "features.py must not append events"
        else:
            assert not writes, f"{module_name} must not import the ledger"


async def test_no_risk_module_imports_an_llm_or_http_client():
    """Explanations are assembled from contributions; nothing calls a model."""
    banned = ("openai", "anthropic", "httpx", "requests", "urllib.request", "aiohttp")
    for path in RISK_DIR.glob("*.py"):
        names = _imports(path)
        offenders = sorted(n for n in names if any(n.startswith(b) for b in banned))
        assert offenders == [], f"{path.name} imports {offenders}"


# --------------------------------------------------------------------------- #
# Fixture: a mission with a full history
# --------------------------------------------------------------------------- #
async def _rich_mission(session) -> uuid.UUID:
    mission = await Orchestrator(merchants=[MockMerchantA()]).run(
        session,
        CreateMissionRequest(
            quantity=1,
            constraints=MissionConstraints(
                category="wireless_earbuds",
                soft_budget_inr=4500,
                hard_limit_inr=4500,
                min_rating=3.5,
                currency="INR",
            ),
        ),
    )
    await session.flush()
    row = await authorization_for_mission(session, mission.id)
    if row is not None and row.status == "PENDING":
        await activate_authorization(session, authorization_id=row.authorization_id)
        mission.state = "AUTHORIZED"
    await session.flush()
    if row is not None:
        await create_payment_intent(
            session,
            capabilities=EXECUTOR,
            mission_id=mission.id,
            authorization_id=row.authorization_id,
            idempotency_key=f"isolation-{mission.id}",
            provider=FakePaymentProvider().name,
        )
    await session.commit()
    return mission.id


async def _census(session) -> dict[str, int]:
    return {
        name: int((await session.execute(select(func.count()).select_from(model))).scalar_one())
        for name, model in _COUNTED_TABLES.items()
    }


# --------------------------------------------------------------------------- #
# 2. Landmines
# --------------------------------------------------------------------------- #
async def test_assessment_touches_no_side_effecting_function(session, monkeypatch):
    """Every irreversible operation raises if reached, naming itself."""
    mission_id = await _rich_mission(session)

    def landmine(name):
        async def _boom(*_args, **_kwargs):
            raise AssertionError(f"the risk engine called {name}")

        return _boom

    import services.audit_ledger.ledger as ledger
    import services.payment_executor.executor as executor
    import services.payment_executor.intents as intents
    import services.payment_executor.reconciliation as reconciliation
    import services.payment_executor.webhooks as webhooks
    import services.security_kernel.authorization as authorization

    for module, name in (
        (authorization, "issue_authorization"),
        (authorization, "activate_authorization"),
        (authorization, "consume_authorization"),
        (authorization, "revoke_authorization"),
        (authorization, "expire_if_stale"),
        (intents, "create_payment_intent"),
        (executor, "dispatch_create"),
        (reconciliation, "reconcile_intent"),
        (webhooks, "handle_webhook"),
        (ledger, "append_event"),
    ):
        monkeypatch.setattr(module, name, landmine(f"{module.__name__}.{name}"))

    assessment = await assess_mission(session, mission_id)
    assert 0.0 <= assessment.score <= 1.0


async def test_assessment_calls_no_merchant(session, monkeypatch):
    """Not even to refresh an offer. The persisted rows are the whole world."""
    mission_id = await _rich_mission(session)

    import services.agent_orchestrator.merchants.transport as transport

    def _boom(*_args, **_kwargs):
        raise AssertionError("the risk engine contacted a merchant")

    monkeypatch.setattr(transport.MerchantTransport, "collect", _boom)
    monkeypatch.setattr(transport.MerchantTransport, "connect", _boom)
    await assess_mission(session, mission_id)


async def test_assessment_calls_no_payment_provider(session, monkeypatch):
    mission_id = await _rich_mission(session)

    async def _boom(*_args, **_kwargs):
        raise AssertionError("the risk engine called a payment provider")

    monkeypatch.setattr(FakePaymentProvider, "create_payment", _boom)
    monkeypatch.setattr(FakePaymentProvider, "get_payment", _boom)
    await assess_mission(session, mission_id)


# --------------------------------------------------------------------------- #
# 3. Row census
# --------------------------------------------------------------------------- #
async def test_assessment_creates_no_rows_in_any_table(session):
    mission_id = await _rich_mission(session)
    before = await _census(session)
    await assess_mission(session, mission_id)
    await session.commit()
    assert await _census(session) == before


async def test_repeated_assessment_never_accumulates_anything(session):
    mission_id = await _rich_mission(session)
    before = await _census(session)
    for _ in range(15):
        await assess_mission(session, mission_id)
        await session.commit()
    assert await _census(session) == before


async def test_assessment_does_not_move_the_mission_or_its_authorization(session):
    mission_id = await _rich_mission(session)
    mission = await session.get(Mission, mission_id)
    row = await authorization_for_mission(session, mission_id)
    snapshot = (mission.state, row.status, row.consumed_at)

    await assess_mission(session, mission_id)
    await session.commit()

    mission = await session.get(Mission, mission_id, populate_existing=True)
    row = await session.get(AuthorizationRow, row.authorization_id, populate_existing=True)
    assert (mission.state, row.status, row.consumed_at) == snapshot


async def test_assessment_does_not_advance_a_payment(session):
    """The outbox must still hold its work afterwards."""
    mission_id = await _rich_mission(session)
    intent = (
        await session.execute(
            select(PaymentIntentRow).where(PaymentIntentRow.mission_id == mission_id)
        )
    ).scalar_one()
    before = (intent.state, intent.attempts, intent.provider_payment_id)

    for _ in range(5):
        await assess_mission(session, mission_id)
    await session.commit()

    reloaded = await session.get(PaymentIntentRow, intent.id, populate_existing=True)
    assert (reloaded.state, reloaded.attempts, reloaded.provider_payment_id) == before

    # The work is still there to do: the outbox event was neither claimed nor
    # completed by the assessment, so a worker still has something to pick up.
    events = (
        (
            await session.execute(
                select(OutboxEventRow).where(OutboxEventRow.payment_intent_id == intent.id)
            )
        )
        .scalars()
        .all()
    )
    assert events, "the assessment consumed the outbox event"
    assert all(event.status == OutboxStatus.PENDING.value for event in events)
    assert all(event.claimed_by is None for event in events)
    assert all(event.attempts == 0 for event in events)
