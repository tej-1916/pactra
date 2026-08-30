"""Focused C1 trust-boundary and authorization-validity regressions."""

from __future__ import annotations

from datetime import timedelta

import pytest
from apps.api.db.models import AuthorizationRow, Offer, OutboxEventRow
from packages.schemas.capability import payment_executor_capabilities
from packages.schemas.domain import PolicyDecision, PolicyOutcome, ReasonCode, as_utc
from packages.schemas.payment import PaymentRequest
from packages.schemas.transaction import (
    BOUND_FIELDS,
    OfferCandidate,
    compute_offer_version,
)
from pydantic import ValidationError
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
from tests.conftest import FIXED_EXPIRY, authorized_mission, make_mission


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
