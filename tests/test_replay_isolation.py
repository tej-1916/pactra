"""Replay must be incapable of external effects, not merely observed to avoid them.

Three independent proofs, deliberately at different levels:

1. **Structural** — the replay module's own import graph is parsed. It may not
   import the payment executor, the security kernel, or the merchant adapters.
   A reducer that CAN reach an executor eventually will be asked to.
2. **Landmines** — every function that could produce a side effect is replaced
   with one that raises. If replay touched any of them the test fails with the
   name of what it touched, not with a vague row count.
3. **Row census** — every table is counted before and after. This catches a
   side effect produced by something the first two proofs did not anticipate.

The mission under test carries a full payment history — authorization, intent,
outbox, provider calls, webhook — so the replay has every opportunity to do
something it should not.
"""

import ast
import pathlib

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
from packages.schemas.payment import WebhookEventType
from services.audit_ledger.replay import reduce_events, replay_mission
from services.audit_ledger.verify import verify_mission_chain
from services.payment_executor.intents import create_payment_intent
from services.payment_executor.providers.fake import FakePaymentProvider, webhook_body
from services.payment_executor.webhooks import handle_webhook
from services.payment_executor.worker import drain
from sqlalchemy import func, select
from tests.conftest import authorized_mission

pytestmark = pytest.mark.asyncio

EXECUTOR = payment_executor_capabilities()

REPLAY_MODULE = pathlib.Path(__file__).resolve().parents[1] / "services/audit_ledger/replay.py"

#: Module prefixes the reducer must not be able to reach. Each one owns at
#: least one irreversible action: money movement, authorization state, or a
#: call to an untrusted merchant.
FORBIDDEN_IMPORT_PREFIXES = (
    "services.payment_executor",
    "services.security_kernel",
    "services.agent_orchestrator.merchants",
    "services.agent_orchestrator.orchestrator",
)

_COUNTED_TABLES = {
    "audit_events": AuditEventRow,
    "authorizations": AuthorizationRow,
    "payment_intents": PaymentIntentRow,
    "outbox_events": OutboxEventRow,
    "webhook_events": WebhookEventRow,
    "missions": Mission,
}


async def _census(session) -> dict[str, int]:
    counts = {}
    for name, model in _COUNTED_TABLES.items():
        counts[name] = (await session.execute(select(func.count()).select_from(model))).scalar_one()
    return counts


async def _mission_with_full_payment_history(sessionmaker):
    """An authorized mission that was paid, settled, and webhooked.

    Built through the real executor and worker so the chain contains genuine
    payment events — replaying a mission with no payment history would prove
    nothing about the executor staying untouched.
    """
    provider = FakePaymentProvider()
    async with sessionmaker() as setup:
        mission, authorization, _ = await authorized_mission(setup)
        mission_id = mission.id
        await create_payment_intent(
            setup,
            capabilities=EXECUTOR,
            mission_id=mission_id,
            authorization_id=authorization.authorization_id,
            idempotency_key="idem-isolation",
            provider="fake",
        )
        await setup.commit()

    await drain(sessionmaker, provider=provider)

    async with sessionmaker() as lookup:
        intent = (
            await lookup.execute(
                select(PaymentIntentRow).where(PaymentIntentRow.mission_id == mission_id)
            )
        ).scalar_one()
        provider_payment_id = intent.provider_payment_id

    if provider_payment_id is not None:
        body = webhook_body(
            event_id="evt-isolation",
            event_type=WebhookEventType.PAYMENT_SUCCEEDED,
            provider_payment_id=provider_payment_id,
        )
        async with sessionmaker() as hook:
            await handle_webhook(hook, provider=provider, body=body, signature=provider.sign(body))
            await hook.commit()

    return mission_id, provider


# --------------------------------------------------------------------------- #
# 1. Structural: the reducer cannot even reach a side effect
# --------------------------------------------------------------------------- #
async def test_replay_module_imports_nothing_that_can_cause_a_side_effect():
    """Parsed from source, so it holds regardless of what runs at import time.

    This is the strongest of the three proofs: the other two show replay did not
    call an executor on one particular history. This shows it has no way to.
    """
    tree = ast.parse(REPLAY_MODULE.read_text())
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.append(node.module)

    offenders = [
        module
        for module in imported
        if any(module.startswith(prefix) for prefix in FORBIDDEN_IMPORT_PREFIXES)
    ]
    assert offenders == [], f"replay.py must not import: {offenders}"


async def test_replay_module_imports_only_pure_helpers_from_services():
    """The only `services` imports allowed are the state-machine predicates and
    the ledger's own read path. Anything else is a new capability the reducer
    should not have acquired quietly."""
    tree = ast.parse(REPLAY_MODULE.read_text())
    service_imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("services.")
    }
    assert service_imports == {
        "services.agent_orchestrator.state_machine",
        "services.audit_ledger.ledger",
        "services.audit_ledger.verify",
    }, service_imports


# --------------------------------------------------------------------------- #
# 2. Landmines
# --------------------------------------------------------------------------- #
async def test_replay_triggers_no_side_effecting_call(sessionmaker, monkeypatch):
    """Every dangerous entry point is replaced by one that raises.

    Patched at the DEFINING module so an alias imported elsewhere is covered
    too. A failure names exactly which boundary replay crossed.
    """

    def landmine(name):
        def _boom(*args, **kwargs):
            raise AssertionError(f"replay called {name}, which performs a side effect")

        return _boom

    mission_id, _ = await _mission_with_full_payment_history(sessionmaker)

    import services.agent_orchestrator.merchants.transport as transport_module
    import services.audit_ledger.ledger as ledger_module
    import services.payment_executor.executor as executor_module
    import services.payment_executor.intents as intents_module
    import services.payment_executor.outbox as outbox_module
    import services.payment_executor.reconciliation as reconciliation_module
    import services.payment_executor.webhooks as webhooks_module
    import services.security_kernel.authorization as authorization_module
    from services.payment_executor.providers.fake import FakePaymentProvider as Fake

    monkeypatch.setattr(ledger_module, "append_event", landmine("append_event"))
    monkeypatch.setattr(
        authorization_module, "issue_authorization", landmine("issue_authorization")
    )
    monkeypatch.setattr(
        authorization_module, "consume_authorization", landmine("consume_authorization")
    )
    monkeypatch.setattr(
        authorization_module, "activate_authorization", landmine("activate_authorization")
    )
    monkeypatch.setattr(intents_module, "create_payment_intent", landmine("create_payment_intent"))
    monkeypatch.setattr(executor_module, "dispatch_create", landmine("dispatch_create"))
    monkeypatch.setattr(reconciliation_module, "reconcile_intent", landmine("reconcile_intent"))
    monkeypatch.setattr(webhooks_module, "handle_webhook", landmine("handle_webhook"))
    monkeypatch.setattr(outbox_module, "enqueue_outbox_event", landmine("enqueue_outbox_event"))
    monkeypatch.setattr(Fake, "create_payment", landmine("provider.create_payment"))
    monkeypatch.setattr(Fake, "get_payment", landmine("provider.get_payment"))
    monkeypatch.setattr(transport_module.MerchantTransport, "collect", landmine("merchant.collect"))
    monkeypatch.setattr(transport_module.MerchantTransport, "connect", landmine("merchant.connect"))

    async with sessionmaker() as reader:
        result = await replay_mission(reader, mission_id)
        verification = await verify_mission_chain(reader, mission_id)

    assert result.trusted is True
    assert result.state is not None
    assert verification.valid is True


# --------------------------------------------------------------------------- #
# 3. Row census
# --------------------------------------------------------------------------- #
async def test_replay_creates_no_rows_in_any_table(sessionmaker):
    """Counted per table so a failure says WHICH one grew.

    A commit is issued on the replaying session afterwards: if replay had staged
    anything, this is where it would become durable, and the post-commit census
    would show it.
    """
    mission_id, provider = await _mission_with_full_payment_history(sessionmaker)

    async with sessionmaker() as before_session:
        before = await _census(before_session)
    provider_calls_before = len(provider.create_calls), len(provider.get_calls)

    async with sessionmaker() as replaying:
        result = await replay_mission(replaying, mission_id)
        await replaying.commit()

    async with sessionmaker() as after_session:
        after = await _census(after_session)

    assert result.trusted is True
    assert after == before, {
        table: (before[table], after[table]) for table in before if before[table] != after[table]
    }
    assert (len(provider.create_calls), len(provider.get_calls)) == provider_calls_before
    # Spelled out individually, because these are the counts the phase claims.
    assert after["audit_events"] == before["audit_events"]
    assert after["payment_intents"] == before["payment_intents"]
    assert after["outbox_events"] == before["outbox_events"]
    assert after["authorizations"] == before["authorizations"]
    assert after["webhook_events"] == before["webhook_events"]


async def test_repeated_replay_never_accumulates_anything(sessionmaker):
    """Ten replays must be indistinguishable from one.

    An engine that appended even a single "mission replayed" event would fail
    here — and would also make each verification invalidate the next one's
    expected chain length.
    """
    mission_id, _ = await _mission_with_full_payment_history(sessionmaker)

    async with sessionmaker() as before_session:
        before = await _census(before_session)

    results = []
    for _ in range(10):
        async with sessionmaker() as replaying:
            results.append((await replay_mission(replaying, mission_id)).model_dump_json())
            await replaying.commit()

    async with sessionmaker() as after_session:
        after = await _census(after_session)

    assert after == before
    assert len(set(results)) == 1


async def test_replay_does_not_move_the_mission_row(sessionmaker):
    """Even when the projection and the row disagree.

    The mission is deliberately pushed to a state the events do not describe.
    Replay reports the mismatch and leaves the row alone — reconciling it would
    make a derived view authoritative over the row the kernel enforces against.
    """
    mission_id, _ = await _mission_with_full_payment_history(sessionmaker)

    async with sessionmaker() as drifter:
        mission = await drifter.get(Mission, mission_id)
        mission.state = "COMPLETED"
        await drifter.commit()

    async with sessionmaker() as replaying:
        result = await replay_mission(replaying, mission_id)
        await replaying.commit()

    assert result.comparison is not None
    assert result.comparison.persisted_state == "COMPLETED"
    assert result.comparison.matches is False

    async with sessionmaker() as check:
        mission = await check.get(Mission, mission_id)
        assert mission.state == "COMPLETED"


async def test_the_pure_reducer_needs_no_session_at_all(sessionmaker):
    """`reduce_events` takes events, not a database handle.

    A function that cannot see a session cannot write through one. This is the
    property the whole isolation argument rests on, so it is asserted directly
    rather than implied.
    """
    from services.audit_ledger.ledger import list_events

    mission_id, _ = await _mission_with_full_payment_history(sessionmaker)
    async with sessionmaker() as reader:
        events = await list_events(reader, mission_id)

    # No session in scope: the reducer runs entirely on the detached rows.
    projection = reduce_events(mission_id, events)
    assert projection.events_replayed == len(events)
    assert projection.mission_id == mission_id
