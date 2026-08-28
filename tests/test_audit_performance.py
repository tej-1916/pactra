"""Measured cost of verification and replay over a large mission history.

This is a MEASUREMENT, not an optimization target. Phase 5 adds no cache, no
index, and no snapshot table — none has been shown to be needed, and a cache in
front of a tamper-evidence check is a way to serve a stale "valid" for a chain
that has since been altered.

The assertions are deliberately loose. A tight threshold on a shared CI machine
fails for reasons that have nothing to do with the code, and a flaky performance
gate teaches people to ignore failures. The bound here only catches an
accidental quadratic; the numbers printed with `-s` are the real result, and
they are the only numbers reported anywhere.
"""

import time
import uuid

import pytest
from apps.api.db.models import Mission
from packages.schemas.domain import EventType, MissionState
from services.audit_ledger.ledger import append_event, list_events
from services.audit_ledger.replay import reduce_events
from services.audit_ledger.verify import verify_events

pytestmark = pytest.mark.asyncio

#: A payment-heavy cycle, so the measured events exercise real reducer branches
#: rather than one cheap handler repeated.
CYCLE = (
    EventType.PAYMENT_ATTEMPTED,
    EventType.PAYMENT_PROVIDER_TIMEOUT,
    EventType.PAYMENT_PROVIDER_UNCERTAIN,
    EventType.PAYMENT_RETRY_SCHEDULED,
    EventType.PAYMENT_RECONCILED,
    EventType.SECURITY_VIOLATION,
)

_STATE_FOR = {
    EventType.PAYMENT_ATTEMPTED: "PROCESSING",
    EventType.PAYMENT_PROVIDER_UNCERTAIN: "PROVIDER_PENDING",
}


async def _long_chain(session, length: int):
    mission = Mission(id=uuid.uuid4(), quantity=1, state=MissionState.CREATED.value)
    session.add(mission)
    await session.flush()

    await append_event(
        session,
        mission_id=mission.id,
        event_type=EventType.MISSION_CREATED,
        actor="orchestrator",
        payload={"raw_query": "benchmark", "quantity": 1},
    )
    intent_id = str(uuid.uuid4())
    for index in range(length - 1):
        event_type = CYCLE[index % len(CYCLE)]
        payload = {
            "payment_intent_id": intent_id,
            "provider": "fake",
            "reason_code": "PAYMENT_PROVIDER_TIMEOUT",
            "index": index,
        }
        state = _STATE_FOR.get(event_type)
        if state is not None:
            payload["state"] = state
        await append_event(
            session,
            mission_id=mission.id,
            event_type=event_type,
            actor="payment-executor",
            payload=payload,
        )
    return mission


@pytest.mark.parametrize("length", [100, 500, 1000])
async def test_verify_and_replay_scale_linearly(session, length, capsys):
    mission = await _long_chain(session, length)
    events = await list_events(session, mission.id)
    assert len(events) == length

    started = time.perf_counter()
    verification = verify_events(mission.id, events)
    verify_seconds = time.perf_counter() - started

    started = time.perf_counter()
    projection = reduce_events(mission.id, events)
    replay_seconds = time.perf_counter() - started

    assert verification.valid is True
    assert verification.events_checked == length
    assert projection.events_replayed == length

    with capsys.disabled():
        print(
            f"\n[phase5-perf] events={length:>4}  "
            f"verify={verify_seconds * 1000:7.2f} ms  "
            f"replay={replay_seconds * 1000:7.2f} ms  "
            f"verify_per_event={verify_seconds / length * 1e6:6.1f} us  "
            f"replay_per_event={replay_seconds / length * 1e6:6.1f} us"
        )

    # Loose by design — see the module docstring. This catches an accidental
    # quadratic, not a millisecond regression.
    assert verify_seconds < 5.0
    assert replay_seconds < 5.0


async def test_verification_cost_is_not_quadratic_in_chain_length(session):
    """Ten times the events must not cost anything like a hundred times the work.

    Measured as a RATIO between two runs in the same process, which cancels out
    machine speed — the thing a wall-clock threshold cannot do.
    """
    small = await _long_chain(session, 100)
    large = await _long_chain(session, 1000)
    small_events = await list_events(session, small.id)
    large_events = await list_events(session, large.id)

    def measure(mission_id, events) -> float:
        started = time.perf_counter()
        for _ in range(3):
            verify_events(mission_id, events)
            reduce_events(mission_id, events)
        return time.perf_counter() - started

    # Warm the interpreter so the first run does not pay import/JIT-ish costs
    # that would be attributed to the smaller chain.
    measure(small.id, small_events)

    small_seconds = measure(small.id, small_events)
    large_seconds = measure(large.id, large_events)

    # Linear would be ~10x. A quadratic implementation would be ~100x. The
    # generous 30x bound distinguishes those two without being flaky.
    assert large_seconds < small_seconds * 30, (
        f"10x the events cost {large_seconds / max(small_seconds, 1e-9):.1f}x the time"
    )
