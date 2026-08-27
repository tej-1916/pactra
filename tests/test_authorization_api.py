"""Authorization lifecycle over the HTTP surface.

Also pins the disclosure rule: the nonce is server-held authorization material
and must never appear in an API response.
"""

import pytest
from packages.schemas.authorization import AuthorizationStatus
from packages.schemas.domain import EventType, MissionState

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


async def _create(client, **c):
    r = await client.post("/api/v1/missions", json=_body(**c))
    assert r.status_code == 201, r.text
    return r.json()


# --------------------------------------------------------------------------- #
# REQUIRE_APPROVAL path
# --------------------------------------------------------------------------- #
async def test_require_approval_mission_has_a_pending_authorization(client):
    mission = await _create(client)
    assert mission["state"] == MissionState.AWAITING_APPROVAL.value

    r = await client.get(f"/api/v1/missions/{mission['id']}/authorization")
    assert r.status_code == 200, r.text
    auth = r.json()
    assert auth["status"] == AuthorizationStatus.PENDING.value
    assert auth["mission_id"] == mission["id"]
    assert len(auth["transaction_digest"]) == 64
    assert auth["binding_version"] == "pactra-txn-bind-v1"
    assert auth["policy_version"] == "policy-v1"
    assert auth["bound_currency"] == "INR"
    assert auth["bound_quantity"] == 1
    assert auth["bound_amount_inr"] == mission["policy_decision"]["requested_amount"]
    assert auth["consumed_at"] is None


async def _actual_nonce(sessionmaker, mission_id: str) -> str:
    """Read the real nonce straight from storage, so the leak tests below check
    the actual secret value rather than merely the absence of a key name."""
    import uuid as _uuid

    from services.security_kernel.authorization import authorization_for_mission

    async with sessionmaker() as s:
        row = await authorization_for_mission(s, _uuid.UUID(mission_id))
        assert row is not None
        return row.nonce


async def test_authorization_response_never_discloses_the_nonce(client, sessionmaker):
    """The nonce is part of the digest preimage. Handing it out would give away
    the one input an attacker cannot otherwise guess."""
    mission = await _create(client)
    nonce = await _actual_nonce(sessionmaker, mission["id"])
    assert len(nonce) == 64  # the real thing, not a placeholder

    r = await client.get(f"/api/v1/missions/{mission['id']}/authorization")
    assert r.status_code == 200
    assert "nonce" not in r.json()
    assert "nonce" not in r.text.lower()
    assert nonce not in r.text


async def test_audit_events_never_disclose_the_nonce(client, sessionmaker):
    mission = await _create(client)
    nonce = await _actual_nonce(sessionmaker, mission["id"])

    r = await client.get(f"/api/v1/missions/{mission['id']}/events")
    assert r.status_code == 200
    assert "nonce" not in r.text.lower()
    assert nonce not in r.text


async def test_mission_and_offer_responses_never_disclose_the_nonce(client, sessionmaker):
    mission = await _create(client)
    nonce = await _actual_nonce(sessionmaker, mission["id"])

    for path in (
        f"/api/v1/missions/{mission['id']}",
        f"/api/v1/offers/{mission['id']}",
    ):
        r = await client.get(path)
        assert r.status_code == 200
        assert nonce not in r.text


async def test_approval_activates_the_authorization_and_authorizes_the_mission(client):
    mission = await _create(client)

    r = await client.post(f"/api/v1/missions/{mission['id']}/authorization/approve")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == AuthorizationStatus.ACTIVE.value

    m = await client.get(f"/api/v1/missions/{mission['id']}")
    assert m.json()["state"] == MissionState.AUTHORIZED.value

    ev = await client.get(f"/api/v1/missions/{mission['id']}/events")
    types = [e["event_type"] for e in ev.json()]
    assert EventType.AUTHORIZATION_CREATED.value in types
    assert EventType.AUTHORIZATION_ACTIVATED.value in types
    # The chain stays contiguous through the authorization events.
    assert [e["sequence"] for e in ev.json()] == list(range(len(ev.json())))


async def test_double_approval_is_refused(client):
    mission = await _create(client)
    first = await client.post(f"/api/v1/missions/{mission['id']}/authorization/approve")
    assert first.status_code == 200

    second = await client.post(f"/api/v1/missions/{mission['id']}/authorization/approve")
    assert second.status_code == 409
    assert second.json()["detail"]["reason_code"] == "MISSION_NOT_AWAITING_APPROVAL"


# --------------------------------------------------------------------------- #
# ALLOW path
# --------------------------------------------------------------------------- #
async def test_allow_path_yields_an_active_authorization(client):
    mission = await _create(client, soft_budget_inr=5000, hard_limit_inr=6000)
    assert mission["state"] == MissionState.AUTHORIZED.value
    assert mission["policy_decision"]["decision"] == "ALLOW"

    r = await client.get(f"/api/v1/missions/{mission['id']}/authorization")
    assert r.status_code == 200
    assert r.json()["status"] == AuthorizationStatus.ACTIVE.value


async def test_approving_an_already_authorized_mission_is_refused(client):
    mission = await _create(client, soft_budget_inr=5000, hard_limit_inr=6000)
    r = await client.post(f"/api/v1/missions/{mission['id']}/authorization/approve")
    assert r.status_code == 409


# --------------------------------------------------------------------------- #
# DENY path: NO VALID AUTHORIZATION -> NO PAYMENT
# --------------------------------------------------------------------------- #
async def test_denied_mission_has_no_authorization(client):
    mission = await _create(client, min_rating=5.0)  # no valid offers
    assert mission["state"] == MissionState.CANCELLED.value

    r = await client.get(f"/api/v1/missions/{mission['id']}/authorization")
    assert r.status_code == 404


async def test_hard_limit_breach_produces_no_authorization(client):
    """HARD LIMIT EXCEEDED -> PAYMENT IMPOSSIBLE, with nothing to replay later."""
    body = _body(soft_budget_inr=100, hard_limit_inr=200)
    r = await client.post("/api/v1/missions", json=body)
    assert r.status_code == 201
    mission = r.json()
    assert mission["policy_decision"]["decision"] == "DENY"

    auth = await client.get(f"/api/v1/missions/{mission['id']}/authorization")
    assert auth.status_code == 404


async def test_cannot_approve_a_denied_mission(client):
    mission = await _create(client, min_rating=5.0)
    r = await client.post(f"/api/v1/missions/{mission['id']}/authorization/approve")
    assert r.status_code == 404


async def test_authorization_of_unknown_mission_is_404(client):
    r = await client.get("/api/v1/missions/00000000-0000-0000-0000-000000000000/authorization")
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
# Version stamps are exposed for auditability
# --------------------------------------------------------------------------- #
async def test_offer_and_policy_versions_are_persisted_and_exposed(client):
    mission = await _create(client)
    assert mission["policy_decision"]["policy_version"] == "policy-v1"
    assert all(o["offer_version"] for o in mission["offers"])
    # Distinct offers have distinct content fingerprints.
    versions = [o["offer_version"] for o in mission["offers"]]
    assert len(set(versions)) == len(versions)


async def test_bound_transaction_matches_the_selected_offer(client):
    mission = await _create(client)
    auth = (await client.get(f"/api/v1/missions/{mission['id']}/authorization")).json()
    selected = next(
        o
        for o in mission["offers"]
        if o["offer_id"] == mission["policy_decision"]["selected_offer_id"]
    )
    assert auth["bound_merchant_id"] == selected["merchant_id"]
    assert auth["bound_product_id"] == selected["product_id"]
    assert auth["offer_version"] == selected["offer_version"]
    assert auth["bound_amount_inr"] == selected["amount_inr"] * mission["quantity"]
