"""LOCAL CRYPTOGRAPHIC APPROVAL PROOF security and stability tests."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from apps.api.db.models import (
    AuthorizationRow,
    OutboxEventRow,
    PaymentIntentRow,
    PolicyDecisionRow,
)
from apps.api.pactra.config import get_settings
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from hypothesis import given
from hypothesis import strategies as st
from packages.schemas.approval import (
    APPROVAL_ALGORITHM,
    APPROVAL_DOMAIN,
    ApprovalScheme,
    approval_message,
)
from packages.schemas.authorization import AuthorizationStatus
from packages.schemas.capability import (
    payment_executor_capabilities,
    security_kernel_capabilities,
)
from packages.schemas.domain import EventType, ReasonCode
from packages.schemas.invariants import InvariantViolation
from packages.schemas.transaction import BINDING_VERSION, BoundTransaction
from services.audit_ledger.ledger import list_events
from services.payment_executor.executor import dispatch_create
from services.payment_executor.intents import MissionNotAuthorized, create_payment_intent
from services.payment_executor.providers.fake import FakePaymentProvider
from services.security_kernel.authorization import (
    AuthorizationExpired,
    AuthorizationNotActive,
    AuthorizationProofFailure,
    TransactionBindingFailure,
    activate_authorization,
    approve_authorization_with_signature,
    generate_nonce,
    issue_authorization,
)
from sqlalchemy import func, select, text
from tests.conftest import FIXED_EXPIRY, approved_transaction, make_mission

EXECUTOR = payment_executor_capabilities()
KERNEL = security_kernel_capabilities()


async def _pending_user_authorization(
    session,
    demo_signer,
    *,
    transaction: BoundTransaction | None = None,
    issued_at: datetime | None = None,
):
    mission = await make_mission(session, state="AWAITING_APPROVAL")
    txn = transaction or approved_transaction(expires_at=FIXED_EXPIRY, nonce=generate_nonce())
    session.add(
        PolicyDecisionRow(
            mission_id=mission.id,
            decision="REQUIRE_APPROVAL",
            policy_version=txn.policy_version,
            reason_codes=["SOFT_BUDGET_EXCEEDED"],
            requested_amount=txn.amount_inr,
            soft_budget=max(1, txn.amount_inr - 1),
            hard_limit=txn.amount_inr,
            selected_offer_id=None,
        )
    )
    await session.flush()
    row = await issue_authorization(
        session,
        capabilities=KERNEL,
        mission_id=mission.id,
        transaction=txn,
        approval_scheme=ApprovalScheme.USER_ED25519,
        issued_at=issued_at,
    )
    message = approval_message(
        authorization_id=row.authorization_id,
        mission_id=row.mission_id,
        binding_version=row.binding_version,
        transaction_digest=row.transaction_digest,
        signing_key_id=demo_signer.signing_key_id,
    )
    return mission, row, txn, message, demo_signer.sign_hex(message)


async def _activate_user(session, demo_signer):
    mission, row, txn, _, signature = await _pending_user_authorization(session, demo_signer)
    activated = await approve_authorization_with_signature(
        session,
        mission_id=mission.id,
        authorization_id=row.authorization_id,
        signing_key_id=demo_signer.signing_key_id,
        signature_hex=signature,
    )
    mission.state = "AUTHORIZED"
    await session.flush()
    return mission, activated, txn, signature


async def _queued_user_payment(session, demo_signer, *, key: str):
    mission, authorization, _, signature = await _activate_user(session, demo_signer)
    result = await create_payment_intent(
        session,
        capabilities=EXECUTOR,
        mission_id=mission.id,
        authorization_id=authorization.authorization_id,
        idempotency_key=key,
        provider="fake",
    )
    event = (
        await session.execute(
            select(OutboxEventRow).where(OutboxEventRow.payment_intent_id == result.intent.id)
        )
    ).scalar_one()
    return mission, authorization, result.intent, event, signature


def _transaction_from_row(row: AuthorizationRow) -> BoundTransaction:
    return BoundTransaction(
        merchant_id=row.bound_merchant_id,
        product_id=row.bound_product_id,
        quantity=row.bound_quantity,
        amount_inr=row.bound_amount_inr,
        currency=row.bound_currency,
        policy_version=row.policy_version,
        offer_version=row.offer_version,
        expires_at=row.expires_at.replace(tzinfo=timezone.utc)
        if row.expires_at.tzinfo is None
        else row.expires_at,
        nonce=row.nonce,
    )


async def _bypass_checks(session, statement: str, parameters: dict) -> None:
    """Simulate storage corruption; never a production write path."""
    await session.execute(text("PRAGMA ignore_check_constraints = ON"))
    try:
        await session.execute(text(statement), parameters)
        await session.flush()
    finally:
        await session.execute(text("PRAGMA ignore_check_constraints = OFF"))


def test_approval_protocol_constants_are_pinned():
    assert APPROVAL_DOMAIN == "pactra-user-approval-v1"
    assert APPROVAL_ALGORITHM == "Ed25519"
    assert BINDING_VERSION == "pactra-txn-bind-v1"


def test_golden_approval_message_byte_vector():
    message = approval_message(
        authorization_id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
        mission_id=uuid.UUID("22222222-2222-4222-8222-222222222222"),
        binding_version="pactra-txn-bind-v1",
        transaction_digest="ab" * 32,
        signing_key_id="demo-user-ed25519-v1",
    )
    assert message.hex() == (
        "7061637472612d757365722d617070726f76616c2d76311f7b22617574686f72697a6174696f6e5f"
        "6964223a5b2273222c2231313131313131312d313131312d343131312d383131312d313131313131"
        "313131313131225d2c2262696e64696e675f76657273696f6e223a5b2273222c227061637472612d"
        "74786e2d62696e642d7631225d2c226d697373696f6e5f6964223a5b2273222c2232323232323232"
        "322d323232322d343232322d383232322d323232323232323232323232225d2c227369676e696e67"
        "5f6b65795f6964223a5b2273222c2264656d6f2d757365722d656432353531392d7631225d2c2274"
        "72616e73616374696f6e5f646967657374223a5b2273222c22616261626162616261626162616261"
        "62616261626162616261626162616261626162616261626162616261626162616261626162616261"
        "626162616261626162225d7d"
    )


def test_approval_message_serialization_is_stable():
    values = dict(
        authorization_id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
        mission_id=uuid.UUID("22222222-2222-4222-8222-222222222222"),
        binding_version="pactra-txn-bind-v1",
        transaction_digest="ab" * 32,
        signing_key_id="demo-user-ed25519-v1",
    )
    assert approval_message(**values) == approval_message(**dict(reversed(values.items())))


@given(
    st.sampled_from(
        [
            "authorization_id",
            "mission_id",
            "binding_version",
            "transaction_digest",
            "signing_key_id",
        ]
    )
)
def test_mutating_any_approval_message_field_invalidates_signature(field):
    private = Ed25519PrivateKey.generate()
    values = dict(
        authorization_id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
        mission_id=uuid.UUID("22222222-2222-4222-8222-222222222222"),
        binding_version="pactra-txn-bind-v1",
        transaction_digest="ab" * 32,
        signing_key_id="demo-user-ed25519-v1",
    )
    signature = private.sign(approval_message(**values))
    mutations = {
        "authorization_id": uuid.UUID("33333333-3333-4333-8333-333333333333"),
        "mission_id": uuid.UUID("44444444-4444-4444-8444-444444444444"),
        "binding_version": "pactra-txn-bind-v2",
        "transaction_digest": "cd" * 32,
        "signing_key_id": "another-demo-key",
    }
    values[field] = mutations[field]
    with pytest.raises(InvalidSignature):
        private.public_key().verify(signature, approval_message(**values))


async def test_valid_signature_is_accepted(session, demo_signer):
    mission, row, _, _, signature = await _pending_user_authorization(session, demo_signer)
    activated = await approve_authorization_with_signature(
        session,
        mission_id=mission.id,
        authorization_id=row.authorization_id,
        signing_key_id=demo_signer.signing_key_id,
        signature_hex=signature,
    )
    assert activated.status == AuthorizationStatus.ACTIVE.value
    assert activated.approval_scheme == ApprovalScheme.USER_ED25519.value
    assert activated.signing_key_id == demo_signer.signing_key_id
    assert activated.approval_signature == signature


async def test_wrong_user_key_is_rejected(session, demo_signer):
    mission, row, _, message, _ = await _pending_user_authorization(session, demo_signer)
    wrong_signature = Ed25519PrivateKey.generate().sign(message).hex()
    with pytest.raises(AuthorizationProofFailure) as caught:
        await approve_authorization_with_signature(
            session,
            mission_id=mission.id,
            authorization_id=row.authorization_id,
            signing_key_id=demo_signer.signing_key_id,
            signature_hex=wrong_signature,
        )
    assert caught.value.reason_code == ReasonCode.AUTHORIZATION_SIGNATURE_INVALID.value
    assert row.status == AuthorizationStatus.PENDING.value


async def test_unknown_signing_key_is_rejected(session, demo_signer):
    mission, row, _, _, signature = await _pending_user_authorization(session, demo_signer)
    with pytest.raises(AuthorizationProofFailure) as caught:
        await approve_authorization_with_signature(
            session,
            mission_id=mission.id,
            authorization_id=row.authorization_id,
            signing_key_id="request-self-enrolled-key",
            signature_hex=signature,
        )
    assert caught.value.reason_code == ReasonCode.AUTHORIZATION_SIGNING_KEY_UNKNOWN.value


async def test_malformed_signature_is_rejected_before_crypto(session, demo_signer):
    mission, row, _, _, _ = await _pending_user_authorization(session, demo_signer)
    with pytest.raises(AuthorizationProofFailure) as caught:
        await approve_authorization_with_signature(
            session,
            mission_id=mission.id,
            authorization_id=row.authorization_id,
            signing_key_id=demo_signer.signing_key_id,
            signature_hex="AA" * 64,
        )
    assert caught.value.reason_code == ReasonCode.AUTHORIZATION_SIGNATURE_MALFORMED.value


async def test_corrupted_signature_is_rejected(session, demo_signer):
    mission, row, _, _, signature = await _pending_user_authorization(session, demo_signer)
    corrupted = ("0" if signature[0] != "0" else "1") + signature[1:]
    with pytest.raises(AuthorizationProofFailure) as caught:
        await approve_authorization_with_signature(
            session,
            mission_id=mission.id,
            authorization_id=row.authorization_id,
            signing_key_id=demo_signer.signing_key_id,
            signature_hex=corrupted,
        )
    assert caught.value.reason_code == ReasonCode.AUTHORIZATION_SIGNATURE_INVALID.value


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("bound_amount_inr", 3800),
        ("bound_merchant_id", "merchant_b"),
        ("bound_product_id", "P2"),
        ("bound_quantity", 2),
        ("policy_version", "policy-v2"),
        ("offer_version", "offer-v2"),
    ],
)
async def test_post_signature_transaction_mutation_is_rejected(session, demo_signer, column, value):
    mission, row, _, _, signature = await _pending_user_authorization(session, demo_signer)
    setattr(row, column, value)
    mutated = _transaction_from_row(row)
    row.transaction_digest = mutated.digest()
    if column == "policy_version":
        decision = (
            await session.execute(
                select(PolicyDecisionRow).where(PolicyDecisionRow.mission_id == mission.id)
            )
        ).scalar_one()
        decision.policy_version = value
    await session.flush()

    with pytest.raises(AuthorizationProofFailure) as caught:
        await approve_authorization_with_signature(
            session,
            mission_id=mission.id,
            authorization_id=row.authorization_id,
            signing_key_id=demo_signer.signing_key_id,
            signature_hex=signature,
        )
    assert caught.value.reason_code == ReasonCode.AUTHORIZATION_SIGNATURE_INVALID.value


async def test_altered_digest_is_rejected_before_proof_acceptance(session, demo_signer):
    mission, row, _, _, signature = await _pending_user_authorization(session, demo_signer)
    row.transaction_digest = "cd" * 32
    await session.flush()
    with pytest.raises(InvariantViolation):
        await approve_authorization_with_signature(
            session,
            mission_id=mission.id,
            authorization_id=row.authorization_id,
            signing_key_id=demo_signer.signing_key_id,
            signature_hex=signature,
        )
    assert row.status == AuthorizationStatus.PENDING.value


async def test_signature_copied_to_another_authorization_and_mission_is_rejected(
    session, demo_signer
):
    _, _, _, _, signature_a = await _pending_user_authorization(session, demo_signer)
    mission_b, row_b, _, _, _ = await _pending_user_authorization(session, demo_signer)
    with pytest.raises(AuthorizationProofFailure) as caught:
        await approve_authorization_with_signature(
            session,
            mission_id=mission_b.id,
            authorization_id=row_b.authorization_id,
            signing_key_id=demo_signer.signing_key_id,
            signature_hex=signature_a,
        )
    assert caught.value.reason_code == ReasonCode.AUTHORIZATION_SIGNATURE_INVALID.value


async def test_expired_signed_approval_is_rejected(session, demo_signer):
    issued = datetime(2026, 1, 1, tzinfo=timezone.utc)
    expires = issued + timedelta(minutes=1)
    txn = approved_transaction(expires_at=expires, nonce=generate_nonce())
    mission, row, _, _, signature = await _pending_user_authorization(
        session,
        demo_signer,
        transaction=txn,
        issued_at=issued,
    )
    with pytest.raises(AuthorizationExpired):
        await approve_authorization_with_signature(
            session,
            mission_id=mission.id,
            authorization_id=row.authorization_id,
            signing_key_id=demo_signer.signing_key_id,
            signature_hex=signature,
            now=expires,
        )


async def test_user_authorization_cannot_use_policy_auto_activation(session, demo_signer):
    _, row, _, _, _ = await _pending_user_authorization(session, demo_signer)
    with pytest.raises(AuthorizationNotActive):
        await activate_authorization(session, authorization_id=row.authorization_id)
    assert row.status == AuthorizationStatus.PENDING.value


async def test_valid_user_approval_can_create_only_one_payment_intent(session, demo_signer):
    mission, authorization, _, _ = await _activate_user(session, demo_signer)
    first = await create_payment_intent(
        session,
        capabilities=EXECUTOR,
        mission_id=mission.id,
        authorization_id=authorization.authorization_id,
        idempotency_key="signed-first",
        provider="fake",
    )
    assert first.created is True
    with pytest.raises(MissionNotAuthorized) as caught:
        await create_payment_intent(
            session,
            capabilities=EXECUTOR,
            mission_id=mission.id,
            authorization_id=authorization.authorization_id,
            idempotency_key="signed-second",
            provider="fake",
        )
    assert "MISSION_NOT_AUTHORIZED" in str(caught.value)
    assert await session.scalar(select(func.count()).select_from(PaymentIntentRow)) == 1


@pytest.mark.parametrize("corruption", ["missing", "invalid"])
async def test_invalid_stored_proof_creates_no_intent_or_outbox(session, demo_signer, corruption):
    mission, authorization, _, _ = await _activate_user(session, demo_signer)
    if corruption == "missing":
        await _bypass_checks(
            session,
            "UPDATE authorizations SET signing_key_id = NULL, approval_signature = NULL "
            "WHERE authorization_id = :authorization_id",
            {"authorization_id": authorization.authorization_id.hex},
        )
    else:
        authorization.approval_signature = "00" * 64
        await session.flush()

    with pytest.raises(AuthorizationProofFailure):
        await create_payment_intent(
            session,
            capabilities=EXECUTOR,
            mission_id=mission.id,
            authorization_id=authorization.authorization_id,
            idempotency_key=f"bad-proof-{corruption}",
            provider="fake",
        )
    assert await session.scalar(select(func.count()).select_from(PaymentIntentRow)) == 0
    assert await session.scalar(select(func.count()).select_from(OutboxEventRow)) == 0


async def test_user_authorization_cannot_downgrade_to_policy_auto(session, demo_signer):
    mission, authorization, _, _ = await _activate_user(session, demo_signer)
    await _bypass_checks(
        session,
        "UPDATE authorizations SET approval_scheme = 'POLICY_AUTO', "
        "signing_key_id = NULL, approval_signature = NULL "
        "WHERE authorization_id = :authorization_id",
        {"authorization_id": authorization.authorization_id.hex},
    )
    with pytest.raises(AuthorizationProofFailure) as caught:
        await create_payment_intent(
            session,
            capabilities=EXECUTOR,
            mission_id=mission.id,
            authorization_id=authorization.authorization_id,
            idempotency_key="downgrade-refused",
            provider="fake",
        )
    assert caught.value.reason_code == ReasonCode.AUTHORIZATION_APPROVAL_SCHEME_INVALID.value


@pytest.mark.parametrize("corruption", ["missing", "invalid"])
async def test_dispatch_rejects_bad_proof_before_provider_io(session, demo_signer, corruption):
    _, authorization, intent, event, _ = await _queued_user_payment(
        session, demo_signer, key=f"dispatch-{corruption}"
    )
    if corruption == "missing":
        await _bypass_checks(
            session,
            "UPDATE authorizations SET signing_key_id = NULL, approval_signature = NULL "
            "WHERE authorization_id = :authorization_id",
            {"authorization_id": authorization.authorization_id.hex},
        )
    else:
        authorization.approval_signature = "00" * 64
        await session.flush()
    provider = FakePaymentProvider()
    with pytest.raises(AuthorizationProofFailure):
        await dispatch_create(
            session,
            capabilities=EXECUTOR,
            provider=provider,
            intent=intent,
            event=event,
        )
    assert provider.get_calls == []
    assert provider.create_calls == []


async def test_fenced_create_reverifies_user_proof_after_preflight_before_create(
    session, demo_signer
):
    _, authorization, intent, event, _ = await _queued_user_payment(
        session, demo_signer, key="fenced-post-preflight-proof"
    )

    class CorruptAfterPreflightProvider(FakePaymentProvider):
        create_retries_are_idempotent = False

        async def get_payment(self, **kwargs):
            result = await super().get_payment(**kwargs)
            authorization.approval_signature = "00" * 64
            return result

    provider = CorruptAfterPreflightProvider()
    with pytest.raises(AuthorizationProofFailure):
        await dispatch_create(
            session,
            capabilities=EXECUTOR,
            provider=provider,
            intent=intent,
            event=event,
        )

    await session.refresh(intent)
    assert intent.provider_create_fenced_at is not None
    assert intent.state == "QUEUED"
    assert provider.get_calls
    assert provider.create_calls == []


async def test_fenced_create_reverifies_transaction_binding_after_preflight_before_create(
    session, demo_signer
):
    _, _, intent, event, _ = await _queued_user_payment(
        session, demo_signer, key="fenced-post-preflight-binding"
    )

    class CorruptAfterPreflightProvider(FakePaymentProvider):
        create_retries_are_idempotent = False

        async def get_payment(self, **kwargs):
            result = await super().get_payment(**kwargs)
            intent.amount_inr += 1
            return result

    provider = CorruptAfterPreflightProvider()
    with pytest.raises(TransactionBindingFailure):
        await dispatch_create(
            session,
            capabilities=EXECUTOR,
            provider=provider,
            intent=intent,
            event=event,
        )

    await session.refresh(intent)
    assert intent.provider_create_fenced_at is not None
    assert intent.state == "QUEUED"
    assert provider.get_calls
    assert provider.create_calls == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("mission_id", uuid.UUID("55555555-5555-4555-8555-555555555555")),
        ("transaction_digest", "ef" * 32),
        ("merchant_id", "mutated-merchant"),
        ("amount_inr", 999999),
        ("currency", "USD"),
    ],
)
async def test_queued_payment_intent_mutation_is_rejected_before_provider_io(
    session, demo_signer, field, value
):
    _, _, intent, event, _ = await _queued_user_payment(
        session, demo_signer, key=f"intent-mutation-{field}"
    )
    setattr(intent, field, value)
    await session.flush()
    provider = FakePaymentProvider()
    with pytest.raises(TransactionBindingFailure):
        await dispatch_create(
            session,
            capabilities=EXECUTOR,
            provider=provider,
            intent=intent,
            event=event,
        )
    assert provider.get_calls == []
    assert provider.create_calls == []


async def test_success_audit_has_safe_proof_metadata_only(session, demo_signer):
    mission, row, _, _, signature = await _pending_user_authorization(session, demo_signer)
    await approve_authorization_with_signature(
        session,
        mission_id=mission.id,
        authorization_id=row.authorization_id,
        signing_key_id=demo_signer.signing_key_id,
        signature_hex=signature,
    )
    events = await list_events(session, mission.id)
    activated = [e for e in events if e.event_type == EventType.AUTHORIZATION_ACTIVATED.value]
    assert len(activated) == 1
    payload = activated[0].payload
    assert payload["approval_scheme"] == ApprovalScheme.USER_ED25519.value
    assert payload["signing_key_id"] == demo_signer.signing_key_id
    assert payload["transaction_digest"] == row.transaction_digest
    serialized = json.dumps(payload)
    assert "signature" not in serialized.lower()
    assert signature not in serialized


async def test_rejected_signature_audit_is_durable_over_http(client, demo_signer):
    created = await client.post(
        "/api/v1/missions",
        json={
            "raw_query": "signed approval audit",
            "quantity": 1,
            "constraints": {
                "category": "wireless_earbuds",
                "soft_budget_inr": 3000,
                "hard_limit_inr": 4500,
                "min_rating": 4.2,
                "currency": "INR",
            },
        },
    )
    mission_id = created.json()["id"]
    rejected = await client.post(
        f"/api/v1/missions/{mission_id}/authorization/approve",
        json={"signing_key_id": demo_signer.signing_key_id, "signature": "00" * 64},
    )
    assert rejected.status_code == 409
    assert (
        rejected.json()["detail"]["reason_code"] == ReasonCode.AUTHORIZATION_SIGNATURE_INVALID.value
    )
    events = (await client.get(f"/api/v1/missions/{mission_id}/events")).json()
    failures = [
        event
        for event in events
        if event["event_type"] == EventType.SECURITY_VIOLATION.value
        and event["payload"].get("reason_code") == ReasonCode.AUTHORIZATION_SIGNATURE_INVALID.value
    ]
    assert len(failures) == 1
    serialized = json.dumps(failures)
    assert "approval_signature" not in serialized
    assert ("00" * 64) not in serialized


async def test_api_refuses_algorithm_and_public_key_self_enrollment(client, demo_signer):
    created = await client.post(
        "/api/v1/missions",
        json={
            "raw_query": "strict approval body",
            "quantity": 1,
            "constraints": {
                "category": "wireless_earbuds",
                "soft_budget_inr": 3000,
                "hard_limit_inr": 4500,
                "min_rating": 4.2,
                "currency": "INR",
            },
        },
    )
    mission_id = created.json()["id"]
    base = {"signing_key_id": demo_signer.signing_key_id, "signature": "00" * 64}
    for extra in ({"algorithm": "Ed25519"}, {"public_key": "00" * 32}):
        response = await client.post(
            f"/api/v1/missions/{mission_id}/authorization/approve",
            json={**base, **extra},
        )
        assert response.status_code == 422


async def test_challenge_displays_bound_transaction_without_nonce(client, demo_signer):
    created = await client.post(
        "/api/v1/missions",
        json={
            "raw_query": "show signer details",
            "quantity": 1,
            "constraints": {
                "category": "wireless_earbuds",
                "soft_budget_inr": 3000,
                "hard_limit_inr": 4500,
                "min_rating": 4.2,
                "currency": "INR",
            },
        },
    )
    mission_id = created.json()["id"]
    response = await client.get(f"/api/v1/missions/{mission_id}/authorization/challenge")
    assert response.status_code == 200
    challenge = response.json()
    assert challenge["approval_scheme"] == ApprovalScheme.USER_ED25519.value
    assert challenge["signing_key_id"] == demo_signer.signing_key_id
    assert set(challenge["transaction"]) == {
        "merchant",
        "product",
        "quantity",
        "amount",
        "currency",
        "expiry",
    }
    assert "nonce" not in response.text.lower()


async def test_malformed_configured_public_key_fails_closed(session, demo_signer, monkeypatch):
    mission, row, _, _, signature = await _pending_user_authorization(session, demo_signer)
    monkeypatch.setenv("DEMO_APPROVER_PUBLIC_KEY_HEX", "not-a-public-key")
    get_settings.cache_clear()
    with pytest.raises(AuthorizationProofFailure) as caught:
        await approve_authorization_with_signature(
            session,
            mission_id=mission.id,
            authorization_id=row.authorization_id,
            signing_key_id=demo_signer.signing_key_id,
            signature_hex=signature,
        )
    assert caught.value.reason_code == ReasonCode.AUTHORIZATION_SIGNING_KEY_UNKNOWN.value


async def test_policy_auto_remains_unsigned_and_distinct(client):
    response = await client.post(
        "/api/v1/missions",
        json={
            "raw_query": "policy auto path",
            "quantity": 1,
            "constraints": {
                "category": "wireless_earbuds",
                "soft_budget_inr": 5000,
                "hard_limit_inr": 6000,
                "min_rating": 4.2,
                "currency": "INR",
            },
        },
    )
    mission_id = response.json()["id"]
    artifact = (await client.get(f"/api/v1/missions/{mission_id}/authorization")).json()
    assert artifact["approval_scheme"] == ApprovalScheme.POLICY_AUTO.value
    assert artifact["signing_key_id"] is None
