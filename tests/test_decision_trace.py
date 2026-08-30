"""C1 Decision Trace schema, semantics, ordering, and redaction contract."""

from __future__ import annotations

from packages.schemas.audit import (
    DecisionStage,
    DecisionTraceEntry,
    DecisionTraceNextAction,
    DecisionTraceVerdict,
)
from packages.schemas.domain import EventType
from services.audit_ledger.replay import TRACE_STAGE_BY_EVENT
from tests.conftest import approve_with_demo_signer


def _mission_payload(*, soft: int, hard: int) -> dict:
    return {
        "raw_query": "C1 decision trace contract",
        "quantity": 1,
        "constraints": {
            "category": "wireless_earbuds",
            "soft_budget_inr": soft,
            "hard_limit_inr": hard,
            "min_rating": 4.2,
            "currency": "INR",
        },
    }


async def _create(client, *, soft: int, hard: int) -> str:
    response = await client.post("/api/v1/missions", json=_mission_payload(soft=soft, hard=hard))
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_trace_schema_and_enums_are_frozen():
    assert set(DecisionTraceEntry.model_fields) == {
        "stage",
        "event_type",
        "verdict",
        "reason_codes",
        "invariant_id",
        "approval_scheme",
        "policy_outcome",
        "payment_state",
        "advisory",
        "next_action",
        "evidence",
        "recorded_at",
    }
    assert {member.value for member in DecisionStage} == {"ADMIT", "BIND", "EXECUTE"}
    assert {member.value for member in DecisionTraceVerdict} == {
        "ACCEPTED",
        "REFUSED",
        "PENDING",
        "SUCCEEDED",
        "FAILED",
        "IGNORED",
        "ADVISORY",
    }
    assert {member.value for member in DecisionTraceNextAction} == {
        "CONTINUE_ADMIT",
        "CONTINUE_BIND",
        "AWAIT_USER_SIGNATURE",
        "CREATE_PAYMENT_INTENT",
        "DISPATCH_PAYMENT",
        "AWAIT_PROVIDER",
        "RECONCILE_PAYMENT",
        "RETRY_PAYMENT",
        "NONE",
    }


def test_every_runtime_event_has_an_admit_bind_execute_stage():
    assert set(TRACE_STAGE_BY_EVENT) == set(EventType)


async def test_existing_replay_endpoint_returns_deterministic_ordered_trace(client):
    mission_id = await _create(client, soft=5000, hard=6000)
    payment = await client.post(
        f"/api/v1/missions/{mission_id}/payment",
        headers={"Idempotency-Key": "c1-trace-payment"},
    )
    assert payment.status_code == 201, payment.text

    first = await client.get(f"/api/v1/missions/{mission_id}/replay")
    second = await client.get(f"/api/v1/missions/{mission_id}/replay")
    assert first.status_code == second.status_code == 200
    assert first.json()["decision_trace"] == second.json()["decision_trace"]

    trace = first.json()["decision_trace"]
    sequences = [entry["evidence"]["sequence"] for entry in trace]
    assert sequences == sorted(sequences)
    assert len(sequences) == len(set(sequences))

    stages = {entry["event_type"]: entry["stage"] for entry in trace}
    assert stages[EventType.INTENT_PARSED.value] == DecisionStage.ADMIT.value
    assert stages[EventType.AUTHORIZATION_CREATED.value] == DecisionStage.BIND.value
    assert stages[EventType.PAYMENT_INTENT_CREATED.value] == DecisionStage.EXECUTE.value


async def test_policy_auto_trace_never_claims_human_approval(client):
    mission_id = await _create(client, soft=5000, hard=6000)
    body = (await client.get(f"/api/v1/missions/{mission_id}/replay")).json()

    auth_entries = [
        entry
        for entry in body["decision_trace"]
        if entry["event_type"]
        in {EventType.AUTHORIZATION_CREATED.value, EventType.AUTHORIZATION_ACTIVATED.value}
    ]
    assert auth_entries
    assert {entry["approval_scheme"] for entry in auth_entries} == {"POLICY_AUTO"}
    assert all(
        entry["next_action"] != DecisionTraceNextAction.AWAIT_USER_SIGNATURE.value
        for entry in auth_entries
    )
    assert body["state"]["approval_granted"] is False
    assert body["state"]["authorization"]["approval_scheme"] == "POLICY_AUTO"


async def test_user_ed25519_trace_names_proof_without_leaking_it(client, demo_signer):
    mission_id = await _create(client, soft=3000, hard=5000)
    approved = await approve_with_demo_signer(client, mission_id, demo_signer)
    assert approved.status_code == 200, approved.text

    body = (await client.get(f"/api/v1/missions/{mission_id}/replay")).json()
    trace = body["decision_trace"]
    proof_entries = [entry for entry in trace if entry["approval_scheme"] == "USER_ED25519"]
    assert {entry["event_type"] for entry in proof_entries} >= {
        EventType.AUTHORIZATION_CREATED.value,
        EventType.APPROVAL_REQUESTED.value,
        EventType.AUTHORIZATION_ACTIVATED.value,
    }
    assert body["state"]["approval_granted"] is True
    assert body["state"]["authorization"]["approval_scheme"] == "USER_ED25519"

    def walk(value):
        if isinstance(value, dict):
            for key, nested in value.items():
                yield key
                yield from walk(nested)
        elif isinstance(value, list):
            for nested in value:
                yield from walk(nested)
        elif isinstance(value, str):
            yield value

    items = list(walk(trace))
    assert "signature" not in items
    assert "approval_signature" not in items
    assert "private_key" not in items
    assert "approval_message_hex" not in items
    # Ed25519 signatures are 64 bytes / 128 lowercase hex. No such proof value
    # may appear even under an innocuous-looking future field name.
    assert not any(len(item) == 128 and set(item) <= set("0123456789abcdef") for item in items)


async def test_risk_trace_is_explicitly_advisory_and_controls_no_next_action(client):
    mission_id = await _create(client, soft=5000, hard=6000)
    assessed = await client.post(f"/api/v1/missions/{mission_id}/risk/assess")
    assert assessed.status_code == 201, assessed.text

    body = (await client.get(f"/api/v1/missions/{mission_id}/replay")).json()
    risk_entries = [
        entry
        for entry in body["decision_trace"]
        if entry["event_type"] == EventType.RISK_ASSESSED.value
    ]
    assert len(risk_entries) == 1
    assert risk_entries[0]["stage"] == DecisionStage.ADMIT.value
    assert risk_entries[0]["verdict"] == DecisionTraceVerdict.ADVISORY.value
    assert risk_entries[0]["advisory"] is True
    assert risk_entries[0]["next_action"] == DecisionTraceNextAction.NONE.value
