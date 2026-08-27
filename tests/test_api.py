import pytest

pytestmark = pytest.mark.asyncio


def _body(**c):
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
    base["constraints"].update(c)
    return base


async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["payment_test_mode"] is True


async def test_create_mission_end_to_end(client):
    r = await client.post("/api/v1/missions", json=_body())
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["state"] == "AWAITING_APPROVAL"
    assert data["policy_decision"]["decision"] == "REQUIRE_APPROVAL"
    assert len(data["offers"]) == 4
    mission_id = data["id"]

    # events endpoint returns a contiguous, hash-linked chain
    ev = await client.get(f"/api/v1/missions/{mission_id}/events")
    assert ev.status_code == 200
    events = ev.json()
    assert [e["sequence"] for e in events] == list(range(len(events)))

    # offers endpoint
    off = await client.get(f"/api/v1/offers/{mission_id}")
    assert off.status_code == 200
    assert len(off.json()) == 4


async def test_invalid_constraints_rejected(client):
    # soft budget above hard limit -> 422 validation error
    r = await client.post("/api/v1/missions", json=_body())
    body = _body()
    body["constraints"]["soft_budget_inr"] = 9999
    body["constraints"]["hard_limit_inr"] = 100
    r = await client.post("/api/v1/missions", json=body)
    assert r.status_code == 422


async def test_get_missing_mission_404(client):
    r = await client.get("/api/v1/missions/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404
