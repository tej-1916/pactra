"""The risk HTTP surface: read-only by default, explicit when it writes.

Also asserts what the routes CANNOT accept. A route that took a config, a score,
or a capability would undo every server-ownership guarantee below it, so the
absence is checked structurally rather than assumed from the handler bodies.
"""

from __future__ import annotations

import ast
import inspect
import pathlib
import uuid

import pytest
from packages.schemas.domain import EventType

# No module-level asyncio mark: several tests here are pure structural
# checks, and `asyncio_mode = "auto"` already collects the async ones.
ROUTES = pathlib.Path(__file__).resolve().parents[1] / "apps/api/pactra/api/routes_risk.py"

APPROVAL_MISSION = {
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

DENIED_MISSION = {
    "raw_query": "earbuds",
    "quantity": 1,
    "constraints": {
        "category": "wireless_earbuds",
        "soft_budget_inr": 1000,
        "hard_limit_inr": 1500,
        "min_rating": 4.2,
        "currency": "INR",
    },
}


async def _mission(client, body=None) -> str:
    response = await client.post("/api/v1/missions", json=body or APPROVAL_MISSION)
    assert response.status_code == 201
    return response.json()["id"]


# --------------------------------------------------------------------------- #
# GET is read-only
# --------------------------------------------------------------------------- #
async def test_get_risk_returns_an_advisory_assessment(client):
    mission_id = await _mission(client)
    response = await client.get(f"/api/v1/missions/{mission_id}/risk")
    assert response.status_code == 200

    body = response.json()
    assert 0.0 <= body["score"] <= 1.0
    assert body["band"] in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
    assert body["recommendation"] in {
        "PROCEED",
        "REVIEW",
        "REQUIRE_STRONGER_APPROVAL",
        "ESCALATE",
    }
    assert body["advisory"] is True
    assert body["score_semantics"] == "NORMALIZED_RISK_INDEX"
    assert body["policy_decision"] == "REQUIRE_APPROVAL"


async def test_get_risk_appends_no_event(client):
    mission_id = await _mission(client)
    before = len((await client.get(f"/api/v1/missions/{mission_id}/events")).json())
    for _ in range(3):
        await client.get(f"/api/v1/missions/{mission_id}/risk")
    after = len((await client.get(f"/api/v1/missions/{mission_id}/events")).json())
    assert after == before


async def test_get_risk_creates_no_privileged_row(client):
    """Census through the API surface itself.

    Reading rows with a second session would open a nested transaction on the
    shared in-memory SQLite connection the ``client`` fixture already holds — so
    the census is taken through the endpoints, which is also the view a caller
    actually has.
    """
    mission_id = await _mission(client)
    before = (await client.get(f"/api/v1/missions/{mission_id}/authorization")).json()

    for _ in range(3):
        await client.get(f"/api/v1/missions/{mission_id}/risk")

    after = (await client.get(f"/api/v1/missions/{mission_id}/authorization")).json()
    assert after == before

    events = (await client.get(f"/api/v1/missions/{mission_id}/events")).json()
    types = [event["event_type"] for event in events]
    assert EventType.PAYMENT_INTENT_CREATED.value not in types
    assert EventType.AUTHORIZATION_CONSUMED.value not in types


async def test_get_risk_is_repeatable_and_stable(client):
    mission_id = await _mission(client)
    first = (await client.get(f"/api/v1/missions/{mission_id}/risk")).json()
    second = (await client.get(f"/api/v1/missions/{mission_id}/risk")).json()
    assert first["score"] == second["score"]
    assert first["band"] == second["band"]
    assert [f["code"] for f in first["factors"]] == [f["code"] for f in second["factors"]]


async def test_an_unknown_mission_is_a_404(client):
    response = await client.get(f"/api/v1/missions/{uuid.uuid4()}/risk")
    assert response.status_code == 404


# --------------------------------------------------------------------------- #
# POST records, explicitly
# --------------------------------------------------------------------------- #
async def test_post_assess_records_one_event(client):
    mission_id = await _mission(client)
    before = (await client.get(f"/api/v1/missions/{mission_id}/events")).json()

    response = await client.post(f"/api/v1/missions/{mission_id}/risk/assess")
    assert response.status_code == 201

    after = (await client.get(f"/api/v1/missions/{mission_id}/events")).json()
    assert len(after) == len(before) + 1
    assert after[-1]["event_type"] == EventType.RISK_ASSESSED.value
    assert after[-1]["actor"] == "risk-engine"


async def test_the_recorded_event_keeps_the_chain_verifiable(client):
    mission_id = await _mission(client)
    await client.post(f"/api/v1/missions/{mission_id}/risk/assess")
    verify = await client.get(f"/api/v1/missions/{mission_id}/audit/verify")
    assert verify.json()["valid"] is True


async def test_the_recorded_event_replays_inertly(client):
    mission_id = await _mission(client)
    before = (await client.get(f"/api/v1/missions/{mission_id}/replay")).json()["state"]
    await client.post(f"/api/v1/missions/{mission_id}/risk/assess")
    after = (await client.get(f"/api/v1/missions/{mission_id}/replay")).json()["state"]

    assert after["risk_assessments"]
    assert before["risk_assessments"] == []
    for field in ("mission_state", "authorization", "payment", "security_events"):
        assert after[field] == before[field]


async def test_post_assess_creates_no_payment_or_authorization(client):
    mission_id = await _mission(client)
    before = (await client.get(f"/api/v1/missions/{mission_id}/authorization")).json()

    await client.post(f"/api/v1/missions/{mission_id}/risk/assess")

    after = (await client.get(f"/api/v1/missions/{mission_id}/authorization")).json()
    assert after == before

    events = (await client.get(f"/api/v1/missions/{mission_id}/events")).json()
    types = [event["event_type"] for event in events]
    assert EventType.PAYMENT_INTENT_CREATED.value not in types
    assert EventType.PAYMENT_QUEUED.value not in types
    # Exactly one advisory event, and nothing else new.
    assert types.count(EventType.RISK_ASSESSED.value) == 1


async def test_post_assess_on_an_unknown_mission_is_a_404(client):
    response = await client.post(f"/api/v1/missions/{uuid.uuid4()}/risk/assess")
    assert response.status_code == 404


# --------------------------------------------------------------------------- #
# Nothing can be injected through a body
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "hostile",
    [
        {"score": 0.0},
        {"band": "LOW", "recommendation": "PROCEED"},
        {"config": {"saturation_points": 1000.0, "review_threshold": 1.0}},
        {"merchant_trust": 1.0},
        {"capabilities": {"principal": "buyer-agent", "allow": ["payment.execute"]}},
        {"advisory": False},
    ],
)
async def test_a_hostile_body_cannot_change_the_verdict(client, hostile):
    mission_id = await _mission(client)
    clean = (await client.get(f"/api/v1/missions/{mission_id}/risk")).json()
    injected = await client.post(f"/api/v1/missions/{mission_id}/risk/assess", json=hostile)

    assert injected.status_code == 201
    body = injected.json()
    assert body["score"] == clean["score"]
    assert body["band"] == clean["band"]
    assert body["advisory"] is True


async def test_a_high_band_is_still_a_200_not_a_refusal(client):
    """An advisory layer that returned 403 would be enforcing."""
    mission_id = await _mission(client)
    response = await client.get(f"/api/v1/missions/{mission_id}/risk")
    assert response.status_code == 200
    assert response.json()["policy_decision"] == "REQUIRE_APPROVAL"


async def test_a_denied_mission_still_reports_deny_beside_its_risk(client):
    mission_id = await _mission(client, DENIED_MISSION)
    body = (await client.get(f"/api/v1/missions/{mission_id}/risk")).json()
    assert body["policy_decision"] == "DENY"
    assert "HARD_LIMIT_EXCEEDED" in body["policy_reason_codes"]
    assert body["recommendation"] not in {"ALLOW", "DENY"}


# --------------------------------------------------------------------------- #
# Structural: the handlers accept nothing they should not
# --------------------------------------------------------------------------- #
def _handler_parameters() -> dict[str, set[str]]:
    """The parameters of the ROUTE HANDLERS, taken from the router itself.

    Read off ``router.routes`` rather than the module namespace: the module also
    holds the imported ``assess_mission``, which legitimately takes a ``config``
    for tests and the evaluation harness. What matters is that no HANDLER does,
    because a handler parameter is what FastAPI would bind caller input to.
    """
    from apps.api.pactra.api.routes_risk import router

    return {
        route.endpoint.__name__: set(inspect.signature(route.endpoint).parameters)
        for route in router.routes
    }


def test_no_route_handler_accepts_a_config_or_a_score():
    forbidden = {
        "config",
        "score",
        "band",
        "recommendation",
        "weights",
        "threshold",
        "registry",
        "capabilities",
    }
    for name, parameters in _handler_parameters().items():
        assert forbidden.isdisjoint(parameters), f"{name} accepts {forbidden & parameters}"


def test_no_route_handler_declares_a_request_body():
    """A body model is the only way FastAPI would bind caller input."""
    for name, parameters in _handler_parameters().items():
        assert parameters <= {"mission_id", "session"}, f"{name} takes {parameters}"


def test_the_route_module_never_constructs_a_config():
    """Weights must reach the engine from the frozen module binding only."""
    tree = ast.parse(ROUTES.read_text(encoding="utf-8"))
    calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "RiskConfig" not in calls


def test_the_route_module_cannot_reach_the_executor_or_the_kernel_writes():
    tree = ast.parse(ROUTES.read_text(encoding="utf-8"))
    modules = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    }
    for banned in (
        "services.payment_executor.intents",
        "services.payment_executor.executor",
        "services.security_kernel.authorization",
    ):
        assert banned not in modules
