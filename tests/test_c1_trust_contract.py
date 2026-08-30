"""Focused C1 trust-boundary and authorization-validity regressions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from apps.api.db.models import (
    AuthorizationRow,
    Mission,
    Offer,
    OutboxEventRow,
    PaymentIntentRow,
)
from packages.schemas.capability import payment_executor_capabilities
from packages.schemas.domain import (
    CreateMissionRequest,
    EventType,
    MissionState,
    PolicyDecision,
    PolicyOutcome,
    RawMerchantOffer,
    ReasonCode,
    as_utc,
)
from packages.schemas.payment import PaymentRequest
from packages.schemas.transaction import (
    BOUND_FIELDS,
    OfferCandidate,
    compute_offer_version,
)
from pydantic import ValidationError
from services.agent_orchestrator import orchestrator as orchestrator_module
from services.agent_orchestrator.orchestrator import Orchestrator
from services.audit_ledger.ledger import list_events
from services.payment_executor.executor import dispatch_create
from services.payment_executor.intents import create_payment_intent
from services.payment_executor.providers.fake import FakePaymentProvider
from services.payment_executor.registry import registered_provider_names
from services.security_kernel.binding import (
    OFFER_VERSION_INVARIANT,
    BindRefusedOfferChanged,
    build_bound_transaction_from_selected_offer,
)
from sqlalchemy import func, select
from tests.conftest import (
    FIXED_EXPIRY,
    authorized_mission,
    make_constraints,
    make_mission,
)


async def _persist_offer(session, valid_offer) -> Offer:
    dto = valid_offer.to_normalized()
    mission = await make_mission(session)
    row = Offer(
        id=dto.offer_id,
        mission_id=mission.id,
        offer_version=dto.offer_version,
        merchant_id=dto.merchant_id,
        merchant_name=dto.merchant_name,
        merchant_trust=dto.merchant_trust,
        product_id=dto.product_id,
        title=dto.title,
        amount_inr=dto.amount_inr,
        currency=dto.currency,
        rating=dto.rating,
        in_stock=dto.in_stock,
        offered_at=dto.offered_at,
        valid=dto.valid,
        rejection_reasons=[],
        rank=1,
        raw={"provenance": {}},
    )
    session.add(row)
    await session.flush()
    return row


def _decision(row: Offer, *, quantity: int = 1) -> PolicyDecision:
    return PolicyDecision(
        decision=PolicyOutcome.REQUIRE_APPROVAL,
        policy_version="policy-v1",
        reason_codes=[ReasonCode.SOFT_BUDGET_EXCEEDED],
        requested_amount=row.amount_inr * quantity,
        soft_budget=max(1, row.amount_inr - 1),
        hard_limit=row.amount_inr * quantity,
        selected_offer_id=row.id,
    )


def _recompute_row_version(row: Offer) -> str:
    return compute_offer_version(
        merchant_id=row.merchant_id,
        product_id=row.product_id,
        amount_inr=row.amount_inr,
        currency=row.currency,
        rating=row.rating,
        in_stock=row.in_stock,
        offered_at=as_utc(row.offered_at),
    )


class _TimestampedMerchant:
    merchant_id = "merchant_a"

    def __init__(self, offered_at: datetime) -> None:
        self.offered_at = offered_at

    def quote(self, constraints, quantity):
        return [
            RawMerchantOffer(
                merchant_id=self.merchant_id,
                product_id="same-instant-offer",
                title="Timestamped Earbuds",
                price=3799,
                currency="INR",
                rating=4.6,
                in_stock=True,
                offered_at=self.offered_at,
            )
        ]


def _mission_request() -> CreateMissionRequest:
    return CreateMissionRequest(
        raw_query="C1 bind-refusal regression",
        quantity=1,
        constraints=make_constraints(soft_budget_inr=4000, hard_limit_inr=4500),
    )


def test_candidate_selection_cannot_carry_authority_fields(valid_offer):
    """The model/selector may return an ID and nothing that can mint authority."""
    candidate = {"offer_id": str(valid_offer.offer_id)}
    for field, value in {
        "merchant_id": "attacker",
        "product_id": "forged-product",
        "amount_inr": 1,
        "currency": "USD",
        "hard_limit_inr": 999999,
        "approval_scheme": "POLICY_AUTO",
    }.items():
        with pytest.raises(ValidationError):
            OfferCandidate.model_validate({**candidate, field: value})


async def test_bind_uses_reloaded_record_not_mutable_selected_offer(session, valid_offer):
    """An in-memory/agent-derived amount cannot become the bound amount."""
    row = await _persist_offer(session, valid_offer)
    decision = _decision(row)
    selected_version = row.offer_version

    # Mutate the earlier provenance-coupled object after selection. BIND never
    # receives it; it reloads the server-held structured row by ID.
    valid_offer.amount_inr.value = 1
    transaction = await build_bound_transaction_from_selected_offer(
        session,
        mission_id=row.mission_id,
        candidate=OfferCandidate(offer_id=row.id),
        selected_offer_version=selected_version,
        decision=decision,
        quantity=1,
        nonce="a" * 64,
        expires_at=FIXED_EXPIRY,
    )

    assert transaction.amount_inr == row.amount_inr
    assert transaction.amount_inr != valid_offer.amount_inr.value
    assert transaction.merchant_id == row.merchant_id
    assert transaction.product_id == row.product_id


@pytest.mark.parametrize(
    ("field", "changed"),
    [
        ("amount_inr", 4400),
        ("product_id", "changed-product"),
        ("merchant_id", "changed-routing-merchant"),
    ],
    ids=["amount", "product-version", "routing-merchant"],
)
async def test_offer_drift_refuses_bind_with_stable_reason(session, valid_offer, field, changed):
    row = await _persist_offer(session, valid_offer)
    decision = _decision(row)
    selected_version = row.offer_version

    setattr(row, field, changed)
    row.offer_version = _recompute_row_version(row)
    await session.flush()

    with pytest.raises(BindRefusedOfferChanged) as caught:
        await build_bound_transaction_from_selected_offer(
            session,
            mission_id=row.mission_id,
            candidate=OfferCandidate(offer_id=row.id),
            selected_offer_version=selected_version,
            decision=decision,
            quantity=1,
            nonce="b" * 64,
            expires_at=FIXED_EXPIRY,
        )

    assert caught.value.reason_code == ReasonCode.BIND_REFUSED_OFFER_CHANGED.value
    assert caught.value.invariant_id == OFFER_VERSION_INVARIANT
    assert await session.scalar(select(func.count()).select_from(AuthorizationRow)) == 0


async def test_equivalent_offset_and_utc_offer_times_survive_real_orchestrator_round_trip(
    sessionmaker,
):
    utc_instant = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    india_instant = datetime(
        2026,
        1,
        1,
        17,
        30,
        tzinfo=timezone(timedelta(hours=5, minutes=30)),
    )
    mission_ids = []

    for offered_at in (india_instant, utc_instant):
        async with sessionmaker() as writer:
            mission = await Orchestrator(merchants=[_TimestampedMerchant(offered_at)]).run(
                writer, _mission_request()
            )
            assert mission.state == MissionState.AUTHORIZED.value
            mission_ids.append(mission.id)
            await writer.commit()

    async with sessionmaker() as reader:
        rows = (
            (
                await reader.execute(
                    select(Offer)
                    .where(Offer.mission_id.in_(mission_ids))
                    .order_by(Offer.mission_id)
                )
            )
            .scalars()
            .all()
        )
        authorizations = await reader.scalar(
            select(func.count())
            .select_from(AuthorizationRow)
            .where(AuthorizationRow.mission_id.in_(mission_ids))
        )

    assert len(rows) == 2
    assert authorizations == 2
    assert {as_utc(row.offered_at) for row in rows} == {utc_instant}
    assert len({row.offer_version for row in rows}) == 1
    assert all(row.offer_version == _recompute_row_version(row) for row in rows)


@pytest.mark.parametrize(
    ("mutation", "expected_invariant"),
    [
        ("offer_drift", OFFER_VERSION_INVARIANT),
        ("offer_invalidated", "binding.offer_is_valid"),
    ],
)
async def test_bind_refusal_is_a_durable_http_conflict_with_no_privileged_artifacts(
    client,
    sessionmaker,
    monkeypatch,
    mutation,
    expected_invariant,
):
    original_bind = orchestrator_module.build_bound_transaction_from_selected_offer

    async def mutate_after_selection(session, **kwargs):
        row = await session.get(Offer, kwargs["candidate"].offer_id)
        assert row is not None
        if mutation == "offer_drift":
            row.amount_inr += 1
            row.offer_version = _recompute_row_version(row)
        else:
            row.valid = False
        await session.flush()
        return await original_bind(session, **kwargs)

    monkeypatch.setattr(
        orchestrator_module,
        "build_bound_transaction_from_selected_offer",
        mutate_after_selection,
    )

    response = await client.post(
        "/api/v1/missions",
        json=_mission_request().model_dump(mode="json"),
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == {
        "reason_code": ReasonCode.BIND_REFUSED_OFFER_CHANGED.value,
        "invariant_id": expected_invariant,
    }

    async with sessionmaker() as reader:
        mission = (await reader.execute(select(Mission))).scalar_one()
        authorization_count = await reader.scalar(
            select(func.count()).select_from(AuthorizationRow)
        )
        payment_count = await reader.scalar(select(func.count()).select_from(PaymentIntentRow))
        outbox_count = await reader.scalar(select(func.count()).select_from(OutboxEventRow))
        events = await list_events(reader, mission.id)

    assert mission.state == MissionState.POLICY_CHECKED.value
    assert authorization_count == 0
    assert payment_count == 0
    assert outbox_count == 0
    refusals = [
        event
        for event in events
        if event.event_type == EventType.SECURITY_VIOLATION.value
        and event.payload.get("bind_refused") is True
    ]
    assert len(refusals) == 1
    assert refusals[0].payload["reason_code"] == ReasonCode.BIND_REFUSED_OFFER_CHANGED.value
    assert refusals[0].payload["invariant_id"] == expected_invariant

    replay = await client.get(f"/api/v1/missions/{mission.id}/replay")
    assert replay.status_code == 200, replay.text
    replay_body = replay.json()
    assert replay_body["trusted"] is True
    assert replay_body["comparison"]["matches"] is True
    assert replay_body["comparison"]["authorization_matches"] is None
    assert replay_body["comparison"]["payment_matches"] is None
    trace_entries = [
        entry
        for entry in replay_body["decision_trace"]
        if entry["event_type"] == EventType.SECURITY_VIOLATION.value
        and entry["reason_codes"] == [ReasonCode.BIND_REFUSED_OFFER_CHANGED.value]
    ]
    assert len(trace_entries) == 1
    assert trace_entries[0]["stage"] == "BIND"
    assert trace_entries[0]["verdict"] == "REFUSED"
    assert trace_entries[0]["invariant_id"] == expected_invariant


def test_current_variable_routing_fields_are_covered_or_server_fixed():
    """Freeze the C1 routing inventory against silent model expansion."""
    assert set(PaymentRequest.model_fields) == {
        "idempotency_key",
        "amount_inr",
        "currency",
        "merchant_id",
        "transaction_digest_prefix",
    }
    assert {"merchant_id", "amount_inr", "currency"} <= set(BOUND_FIELDS)
    assert not {
        "payee_id",
        "destination",
        "destination_account",
        "settlement_account",
        "transfer_account",
    } & set(PaymentRequest.model_fields)
    # Production cannot choose between accounts/adapters per transaction.
    assert registered_provider_names(app_env="production") == ("razorpay_test",)


async def test_consumed_authorization_remains_dispatchable_after_original_expiry(session):
    """Expiry applies at consumption, not retroactively to durable queued work."""
    mission, authorization, _ = await authorized_mission(session)
    result = await create_payment_intent(
        session,
        capabilities=payment_executor_capabilities(),
        mission_id=mission.id,
        authorization_id=authorization.authorization_id,
        idempotency_key="c1-valid-at-consumption",
        provider="fake",
    )
    event = (
        await session.execute(
            select(OutboxEventRow).where(OutboxEventRow.payment_intent_id == result.intent.id)
        )
    ).scalar_one()
    provider = FakePaymentProvider()

    outcome = await dispatch_create(
        session,
        capabilities=payment_executor_capabilities(),
        provider=provider,
        intent=result.intent,
        event=event,
        now=FIXED_EXPIRY + timedelta(seconds=1),
    )

    assert outcome.provider_called is True
    assert provider.create_calls == ["c1-valid-at-consumption"]
