"""The two Phase 5 HTTP routes.

Both are read-only. The tests below check the response SHAPES the phase
promises, the 404 convention shared with every other mission route, and — most
importantly — that hitting either endpoint does not repair a corrupt chain.
"""

import json
import uuid

import pytest
from apps.api.db.models import AuditEventRow
from packages.schemas.audit import AuditReasonCode, ReplayReasonCode
from sqlalchemy import update

pytestmark = pytest.mark.asyncio

MISSING = "00000000-0000-0000-0000-000000000000"


def _as_text(body) -> str:
    """Serialize a response body so a substring check covers nested fields too.

    Asserting a key is absent from the top level would miss it hiding inside
    `state.payment` or a security-event detail.
    """
    return json.dumps(body)


def _body(**constraints):
    base = {
        "raw_query": "Find earbuds under 4000",
        "quantity": 1,
        "constraints": {
            "category": "wireless_earbuds",
            "soft_budget_inr": 4000,
            "hard_limit_inr": 4500,
            "min_rating": 4.2,
            "currency": "INR",
        },
    }
    base["constraints"].update(constraints)
    return base


async def _mission(client) -> str:
    created = await client.post("/api/v1/missions", json=_body())
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def _corrupt(sessionmaker, mission_id: str, sequence: int) -> None:
    async with sessionmaker() as session:
        await session.execute(
            update(AuditEventRow)
            .where(
                AuditEventRow.mission_id == uuid.UUID(mission_id),
                AuditEventRow.sequence == sequence,
            )
            .values(payload={"tampered": True})
            .execution_options(synchronize_session=False)
        )
        await session.commit()


# --------------------------------------------------------------------------- #
# GET /missions/{id}/audit/verify
# --------------------------------------------------------------------------- #
async def test_verify_reports_a_valid_chain(client):
    mission_id = await _mission(client)
    events = (await client.get(f"/api/v1/missions/{mission_id}/events")).json()

    response = await client.get(f"/api/v1/missions/{mission_id}/audit/verify")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["valid"] is True
    assert body["events_checked"] == len(events)
    assert body["first_invalid_sequence"] is None
    assert body["reason_code"] == AuditReasonCode.AUDIT_VALID.value


async def test_verify_reports_corruption_with_the_breaking_position(client, sessionmaker):
    mission_id = await _mission(client)
    await _corrupt(sessionmaker, mission_id, 5)

    response = await client.get(f"/api/v1/missions/{mission_id}/audit/verify")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["valid"] is False
    assert body["events_checked"] == 5
    assert body["first_invalid_sequence"] == 5
    assert body["reason_code"] == AuditReasonCode.AUDIT_EVENT_HASH_MISMATCH.value


async def test_verify_never_returns_an_event_payload(client, sessionmaker):
    """A verification result reports position and hashes, not content.

    The events endpoint already serves payloads to anyone entitled to read
    them; the verifier has no reason to reproduce a tampered one.
    """
    mission_id = await _mission(client)
    await _corrupt(sessionmaker, mission_id, 3)

    body = (await client.get(f"/api/v1/missions/{mission_id}/audit/verify")).json()
    assert "payload" not in body
    assert "tampered" not in _as_text(body)


async def test_verify_is_repeatable_and_repairs_nothing(client, sessionmaker):
    """Two identical calls over a corrupt chain. If the first had healed
    anything, the second would report a valid chain."""
    mission_id = await _mission(client)
    await _corrupt(sessionmaker, mission_id, 2)

    first = (await client.get(f"/api/v1/missions/{mission_id}/audit/verify")).json()
    second = (await client.get(f"/api/v1/missions/{mission_id}/audit/verify")).json()
    assert first == second
    assert first["valid"] is False

    events = (await client.get(f"/api/v1/missions/{mission_id}/events")).json()
    assert events[2]["payload"] == {"tampered": True}


async def test_verify_404_for_an_unknown_mission(client):
    response = await client.get(f"/api/v1/missions/{MISSING}/audit/verify")
    assert response.status_code == 404
    assert response.json()["detail"] == "mission not found"


# --------------------------------------------------------------------------- #
# GET /missions/{id}/replay
# --------------------------------------------------------------------------- #
async def test_replay_returns_a_trusted_reconstruction(client):
    mission_id = await _mission(client)
    mission = (await client.get(f"/api/v1/missions/{mission_id}")).json()

    response = await client.get(f"/api/v1/missions/{mission_id}/replay")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["audit_valid"] is True
    assert body["trusted"] is True
    assert body["reason_code"] == ReplayReasonCode.REPLAY_OK.value
    assert body["unsupported_events"] == []

    state = body["state"]
    assert state["mission_state"] == mission["state"]
    assert state["policy_decision"] == mission["policy_decision"]["decision"]
    assert state["events_replayed"] == body["events_replayed"]
    assert state["authorization"]["status"] == "PENDING"
    assert body["comparison"]["matches"] is True
    assert body["comparison"]["replay_state"] == body["comparison"]["persisted_state"]


async def test_replay_of_a_corrupt_chain_is_untrusted_and_stateless(client, sessionmaker):
    """The integrity gate, over HTTP.

    `state` is null rather than a best-effort projection: a caller handed a
    state object will use it, and a flag beside it does not stop that.
    """
    mission_id = await _mission(client)
    await _corrupt(sessionmaker, mission_id, 4)

    response = await client.get(f"/api/v1/missions/{mission_id}/replay")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["audit_valid"] is False
    assert body["trusted"] is False
    assert body["reason_code"] == ReplayReasonCode.REPLAY_AUDIT_INVALID.value
    assert body["state"] is None
    assert body["comparison"] is None
    assert body["events_replayed"] == 0
    assert body["verification"]["first_invalid_sequence"] == 4


async def test_replay_never_appends_to_the_chain_it_reads(client):
    """Calling replay three times must not lengthen the mission's history."""
    mission_id = await _mission(client)
    before = (await client.get(f"/api/v1/missions/{mission_id}/events")).json()

    for _ in range(3):
        assert (await client.get(f"/api/v1/missions/{mission_id}/replay")).status_code == 200

    after = (await client.get(f"/api/v1/missions/{mission_id}/events")).json()
    assert after == before
    verify = (await client.get(f"/api/v1/missions/{mission_id}/audit/verify")).json()
    assert verify["events_checked"] == len(before)


async def test_replay_404_for_an_unknown_mission(client):
    response = await client.get(f"/api/v1/missions/{MISSING}/replay")
    assert response.status_code == 404
    assert response.json()["detail"] == "mission not found"


async def test_replay_never_returns_the_authorization_nonce(client):
    """The nonce was never written to an audit payload, so replay cannot leak
    it. Asserted anyway, because "cannot" is a claim worth pinning."""
    mission_id = await _mission(client)
    body = (await client.get(f"/api/v1/missions/{mission_id}/replay")).json()
    assert "nonce" not in _as_text(body)
