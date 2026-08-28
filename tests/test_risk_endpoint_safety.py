"""Endpoint-level proof that risk cannot move money, and cannot leak.

Everything here is measured through the HTTP surface a client actually reaches,
because that is the surface an attacker reaches. The unit-level equivalents live
in ``test_risk_isolation.py``; these exist because "the function is read-only"
and "the endpoint is read-only" are different claims — a route can add a side
effect the function never had.

The census is taken through the API rather than a second database session: the
``client`` fixture holds the only connection to the in-memory database, and a
parallel session would open a nested transaction rather than observe one.
"""

from __future__ import annotations

import json
import uuid

import pytest
from packages.schemas.domain import EventType

MISSION = {
    "raw_query": "earbuds",
    "quantity": 1,
    "constraints": {
        "category": "wireless_earbuds",
        "soft_budget_inr": 4000,
        "hard_limit_inr": 4500,
        "min_rating": 4.2,
        "currency": "INR",
    },
}


async def _mission(client) -> str:
    response = await client.post("/api/v1/missions", json=MISSION)
    assert response.status_code == 201
    return response.json()["id"]


async def _snapshot(client, mission_id: str) -> dict:
    """Everything a client can observe about a mission's privileged state."""
    return {
        "mission": (await client.get(f"/api/v1/missions/{mission_id}")).json(),
        "authorization": (await client.get(f"/api/v1/missions/{mission_id}/authorization")).json(),
        "events": [
            {k: e[k] for k in ("sequence", "event_type", "actor", "event_hash")}
            for e in (await client.get(f"/api/v1/missions/{mission_id}/events")).json()
        ],
        "verify": (await client.get(f"/api/v1/missions/{mission_id}/audit/verify")).json(),
        "replay": (await client.get(f"/api/v1/missions/{mission_id}/replay")).json()["state"],
    }


# --------------------------------------------------------------------------- #
# GET /risk changes absolutely nothing
# --------------------------------------------------------------------------- #
async def test_get_risk_leaves_every_observable_byte_unchanged(client):
    mission_id = await _mission(client)
    before = await _snapshot(client, mission_id)

    for _ in range(5):
        assert (await client.get(f"/api/v1/missions/{mission_id}/risk")).status_code == 200

    assert await _snapshot(client, mission_id) == before


async def test_get_risk_adds_no_event_of_any_type(client):
    mission_id = await _mission(client)
    before = [
        e["event_type"] for e in (await client.get(f"/api/v1/missions/{mission_id}/events")).json()
    ]
    await client.get(f"/api/v1/missions/{mission_id}/risk")
    after = [
        e["event_type"] for e in (await client.get(f"/api/v1/missions/{mission_id}/events")).json()
    ]
    assert after == before
    assert EventType.RISK_ASSESSED.value not in after


# --------------------------------------------------------------------------- #
# POST /risk/assess adds exactly one event and changes nothing else
# --------------------------------------------------------------------------- #
async def test_post_assess_adds_exactly_one_event_and_it_is_risk_assessed(client):
    mission_id = await _mission(client)
    before = (await client.get(f"/api/v1/missions/{mission_id}/events")).json()

    assert (await client.post(f"/api/v1/missions/{mission_id}/risk/assess")).status_code == 201

    after = (await client.get(f"/api/v1/missions/{mission_id}/events")).json()
    assert len(after) == len(before) + 1

    # The prefix is byte-identical: no earlier event was rewritten.
    assert [e["event_hash"] for e in after[: len(before)]] == [e["event_hash"] for e in before]
    new = after[-1]
    assert new["event_type"] == EventType.RISK_ASSESSED.value
    assert new["actor"] == "risk-engine"
    # And it is the ONLY new type, not merely the last one.
    assert set(e["event_type"] for e in after) - set(e["event_type"] for e in before) == {
        EventType.RISK_ASSESSED.value
    }


async def test_post_assess_moves_no_mission_authorization_or_payment(client):
    mission_id = await _mission(client)
    before = await _snapshot(client, mission_id)

    await client.post(f"/api/v1/missions/{mission_id}/risk/assess")
    after = await _snapshot(client, mission_id)

    assert after["mission"] == before["mission"]
    assert after["authorization"] == before["authorization"]
    assert after["verify"]["valid"] is True
    # Everything in the replayed projection except the advisory list.
    for field, value in before["replay"].items():
        if field in ("risk_assessments", "events_replayed"):
            continue
        assert after["replay"][field] == value, field


async def test_repeated_assess_adds_one_event_each_and_nothing_else(client):
    mission_id = await _mission(client)
    baseline = await _snapshot(client, mission_id)

    for expected in range(1, 4):
        await client.post(f"/api/v1/missions/{mission_id}/risk/assess")
        events = (await client.get(f"/api/v1/missions/{mission_id}/events")).json()
        risk_events = [e for e in events if e["event_type"] == EventType.RISK_ASSESSED.value]
        assert len(risk_events) == expected

    after = await _snapshot(client, mission_id)
    assert after["mission"] == baseline["mission"]
    assert after["authorization"] == baseline["authorization"]
    assert after["verify"]["valid"] is True


# --------------------------------------------------------------------------- #
# The recorded payload must not leak
# --------------------------------------------------------------------------- #
#: Every secret-shaped thing the system holds. Checked by NAME against the
#: payload keys AND by VALUE against the serialized payload, because a leak is
#: as likely to be an unnamed value as a helpfully-labelled one.
FORBIDDEN_KEYS = (
    "nonce",
    "secret",
    "webhook_secret",
    "signature",
    "credential",
    "password",
    "token",
    "api_key",
    "transaction_digest",
    "weights",
    "weight",
    "feature_values",
    "raw",
)


async def test_the_recorded_payload_contains_no_secret_shaped_key(client):
    mission_id = await _mission(client)
    await client.post(f"/api/v1/missions/{mission_id}/risk/assess")

    events = (await client.get(f"/api/v1/missions/{mission_id}/events")).json()
    payload = next(e["payload"] for e in events if e["event_type"] == EventType.RISK_ASSESSED.value)
    blob = json.dumps(payload).lower()
    for forbidden in FORBIDDEN_KEYS:
        assert forbidden not in payload, f"payload key {forbidden!r}"
        assert forbidden not in blob, f"payload text contains {forbidden!r}"


async def test_the_recorded_payload_never_contains_the_authorization_nonce(session):
    """By VALUE, not by key name. The nonce is server-held entropy that Phase 3
    never returns and never audits; a risk payload must not be the first thing
    to publish it.

    Driven through the session rather than the client because reading the nonce
    needs database access, and the ``client`` fixture holds the only connection
    to the in-memory database — a second session there opens a nested
    transaction rather than observing one.
    """
    from apps.api.db.models import AuthorizationRow
    from packages.schemas.domain import CreateMissionRequest, MissionConstraints
    from services.agent_orchestrator.merchants.mock_merchants import MockMerchantA
    from services.agent_orchestrator.orchestrator import Orchestrator
    from services.audit_ledger.ledger import list_events
    from services.risk_engine.engine import assess_mission, record_assessment
    from sqlalchemy import select

    mission = await Orchestrator(merchants=[MockMerchantA()]).run(
        session,
        CreateMissionRequest(quantity=1, constraints=MissionConstraints(**MISSION["constraints"])),
    )
    await session.commit()

    assessment = await assess_mission(session, mission.id)
    await record_assessment(session, assessment)
    await session.commit()

    nonces = list((await session.execute(select(AuthorizationRow.nonce))).scalars().all())
    assert nonces, "fixture produced no authorization to check against"

    events = await list_events(session, mission.id)
    blob = json.dumps([e.payload for e in events], default=str)
    for nonce in nonces:
        assert nonce not in blob
        # The prefix rule: not even a leading fragment of the nonce.
        assert nonce[:16] not in blob


async def test_the_recorded_payload_carries_only_the_declared_fields(client):
    """An allow-list, not a deny-list: a payload gains fields over time, and a
    deny-list silently starts publishing whatever is added next."""
    mission_id = await _mission(client)
    await client.post(f"/api/v1/missions/{mission_id}/risk/assess")

    events = (await client.get(f"/api/v1/missions/{mission_id}/events")).json()
    payload = next(e["payload"] for e in events if e["event_type"] == EventType.RISK_ASSESSED.value)
    assert set(payload) == {
        "assessment_id",
        "score",
        "band",
        "recommendation",
        "engine_version",
        "model_type",
        "model_version",
        "score_semantics",
        "factor_codes",
        "advisory",
        "history_available",
        "cold_start",
        "audit_chain_verified",
    }


async def test_the_response_body_exposes_no_secret_either(client):
    """The API response is wider than the audit payload — it carries feature
    values and explanations — so it gets its own check."""
    mission_id = await _mission(client)
    body = (await client.get(f"/api/v1/missions/{mission_id}/risk")).json()
    blob = json.dumps(body).lower()
    for forbidden in ("nonce", "secret", "signature", "password", "api_key", "credential"):
        assert forbidden not in blob

    # A digest PREFIX is permitted and a full digest is not.
    prefix = body.get("transaction_digest_prefix")
    if prefix is not None:
        assert len(prefix) == 16


# --------------------------------------------------------------------------- #
# Nothing can be injected — body, query string, or merchant payload
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "query",
    [
        "?risk_score=0",
        "?score=0&band=LOW",
        "?review_threshold=1.0",
        "?weights=%7B%22replay_attempt_weight%22%3A0%7D",
        "?config=%7B%22saturation_points%22%3A1000%7D",
        "?merchant_trust=1.0",
        "?advisory=false",
    ],
)
async def test_query_parameters_cannot_change_the_verdict(client, query):
    """Neither handler declares a query parameter, so FastAPI binds none."""
    mission_id = await _mission(client)
    clean = (await client.get(f"/api/v1/missions/{mission_id}/risk")).json()
    injected = (await client.get(f"/api/v1/missions/{mission_id}/risk{query}")).json()

    assert injected["score"] == clean["score"]
    assert injected["band"] == clean["band"]
    assert injected["recommendation"] == clean["recommendation"]
    assert injected["advisory"] is True


async def test_a_body_on_the_read_endpoint_cannot_change_the_verdict(client):
    mission_id = await _mission(client)
    clean = (await client.get(f"/api/v1/missions/{mission_id}/risk")).json()
    injected = await client.request(
        "GET",
        f"/api/v1/missions/{mission_id}/risk",
        json={"score": 0.0, "config": {"review_threshold": 1.0}},
    )
    assert injected.status_code == 200
    assert injected.json()["score"] == clean["score"]


async def test_an_injected_body_still_records_the_server_computed_verdict(client):
    mission_id = await _mission(client)
    clean = (await client.get(f"/api/v1/missions/{mission_id}/risk")).json()

    await client.post(
        f"/api/v1/missions/{mission_id}/risk/assess",
        json={"score": 0.0, "band": "LOW", "recommendation": "PROCEED"},
    )
    events = (await client.get(f"/api/v1/missions/{mission_id}/events")).json()
    payload = next(e["payload"] for e in events if e["event_type"] == EventType.RISK_ASSESSED.value)
    assert payload["score"] == pytest.approx(clean["score"], abs=1e-6)
    assert payload["band"] == clean["band"]


# --------------------------------------------------------------------------- #
# Failure handling: never fail open into authority
# --------------------------------------------------------------------------- #
async def test_an_extraction_failure_surfaces_as_an_error_not_a_clean_score(client, monkeypatch):
    """A risk engine that returned 0.0 when it broke would report "nothing to
    see here" for a mission it never actually examined. It must fail loudly
    instead — and, being advisory, its failure must change nothing.
    """
    mission_id = await _mission(client)
    before = await _snapshot(client, mission_id)

    import services.risk_engine.engine as engine_module

    async def _broken(*_args, **_kwargs):
        raise RuntimeError("feature extraction exploded")

    monkeypatch.setattr(engine_module, "load_mission_facts", _broken)

    with pytest.raises(RuntimeError):
        await client.get(f"/api/v1/missions/{mission_id}/risk")

    monkeypatch.undo()
    after = await _snapshot(client, mission_id)
    assert after["mission"] == before["mission"]
    assert after["authorization"] == before["authorization"]
    assert after["verify"]["valid"] is True


async def test_a_failed_assessment_records_no_event(client, monkeypatch):
    """A failure must not leave a half-written advisory record behind."""
    mission_id = await _mission(client)
    before = len((await client.get(f"/api/v1/missions/{mission_id}/events")).json())

    import services.risk_engine.engine as engine_module

    async def _broken(*_args, **_kwargs):
        raise RuntimeError("scoring exploded")

    monkeypatch.setattr(engine_module, "load_mission_facts", _broken)
    with pytest.raises(RuntimeError):
        await client.post(f"/api/v1/missions/{mission_id}/risk/assess")
    monkeypatch.undo()

    after = len((await client.get(f"/api/v1/missions/{mission_id}/events")).json())
    assert after == before


async def test_the_deterministic_path_is_unaffected_by_a_broken_risk_engine(client, monkeypatch):
    """The whole point of advisory: the kernel does not depend on it.

    With the risk engine replaced by something that always raises, a mission
    still runs end to end, still reaches a policy decision, still mints an
    authorization, and still verifies.
    """
    import services.risk_engine.engine as engine_module

    async def _broken(*_args, **_kwargs):
        raise RuntimeError("risk engine is down")

    monkeypatch.setattr(engine_module, "load_mission_facts", _broken)

    response = await client.post("/api/v1/missions", json=MISSION)
    assert response.status_code == 201
    mission_id = response.json()["id"]

    assert response.json()["policy_decision"]["decision"] == "REQUIRE_APPROVAL"
    assert (await client.get(f"/api/v1/missions/{mission_id}/authorization")).status_code == 200
    assert (await client.get(f"/api/v1/missions/{mission_id}/audit/verify")).json()["valid"] is True

    approved = await client.post(f"/api/v1/missions/{mission_id}/authorization/approve")
    assert approved.status_code == 200
    assert approved.json()["status"] == "ACTIVE"


async def test_an_unknown_mission_is_a_404_not_a_zero_score(client):
    """A LOW score for a mission that does not exist is the wrong default."""
    for method, suffix in (("get", "/risk"), ("post", "/risk/assess")):
        response = await getattr(client, method)(f"/api/v1/missions/{uuid.uuid4()}{suffix}")
        assert response.status_code == 404
        assert "score" not in response.json()
