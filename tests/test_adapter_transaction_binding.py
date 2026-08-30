"""Adapter-originated candidates reuse Phase 3 transaction binding unchanged."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from apps.api.db.models import Mission
from packages.schemas.approval import ApprovalScheme
from packages.schemas.authorization import AuthorizationStatus
from packages.schemas.capability import security_kernel_capabilities
from packages.schemas.transaction import BoundTransaction
from services.adapters import translate
from services.adapters.models import AdapterFamily, SourceIdentity
from services.security_kernel.authorization import (
    TransactionBindingFailure,
    activate_authorization,
    consume_authorization,
    generate_nonce,
    issue_authorization,
    load_authorization,
)

pytestmark = pytest.mark.asyncio

ADAPTER = "pactra.authorization-intent.v1"
VERSION = "1.0"
EXPIRY = datetime(2030, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
SOURCE = SourceIdentity(claimed_id="external-agent", channel="pytest")


def intent(**overrides):
    payload = {
        "protocol": "pactra.authorization-intent",
        "merchant_id": "merchant_a",
        "product_id": "P1",
        "quantity": 1,
        "amount_inr": 3799,
        "currency": "INR",
        "expires_at": EXPIRY.isoformat(),
    }
    payload.update(overrides)
    return payload


def transaction_from(payload: dict, *, nonce: str) -> BoundTransaction:
    candidate = translate(
        ADAPTER,
        family=AdapterFamily.PAYMENT_AUTHORIZATION,
        protocol_version=VERSION,
        payload=payload,
        source=SOURCE,
    ).canonical_payload
    return BoundTransaction(
        merchant_id=candidate.claimed_merchant_id,
        product_id=candidate.claimed_product_id,
        quantity=candidate.claimed_quantity,
        amount_inr=candidate.claimed_amount_inr,
        currency=candidate.claimed_currency,
        policy_version="policy-v1",
        offer_version="offer-v1",
        expires_at=EXPIRY,
        nonce=nonce,
    )


@pytest.mark.parametrize(
    ("field", "mutated"),
    [
        ("amount_inr", 4399),
        ("currency", "USD"),
        ("merchant_id", "merchant_b"),
        ("product_id", "P2"),
        ("quantity", 2),
    ],
)
async def test_every_requested_adapter_originated_mutation_invalidates_authorization(
    session, field, mutated
):
    nonce = generate_nonce()
    original = transaction_from(intent(), nonce=nonce)
    changed = transaction_from(intent(**{field: mutated}), nonce=nonce)
    assert changed.digest() != original.digest()

    mission_id = uuid.uuid4()
    session.add(Mission(id=mission_id, quantity=1, state="POLICY_CHECKED"))
    await session.flush()
    row = await issue_authorization(
        session,
        capabilities=security_kernel_capabilities(),
        mission_id=mission_id,
        transaction=original,
        approval_scheme=ApprovalScheme.POLICY_AUTO,
    )
    await activate_authorization(session, authorization_id=row.authorization_id)

    with pytest.raises(TransactionBindingFailure):
        await consume_authorization(
            session,
            authorization_id=row.authorization_id,
            transaction=changed,
        )

    reloaded = await load_authorization(session, row.authorization_id)
    assert reloaded is not None
    assert reloaded.status == AuthorizationStatus.ACTIVE.value
    assert reloaded.consumed_at is None
