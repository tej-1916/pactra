"""The payment executor enforces its own privileged boundary.

The brief is explicit that the executor must not rely on the caller having
checked capability earlier. These tests attack the boundary directly rather than
attacking it through the API, because an HTTP-level test only proves the route
is wired correctly — it says nothing about whether the service refuses a caller
that reached it another way (an in-process tool call, a future adapter, a bug).
"""

import uuid

import pytest
from packages.schemas.authorization import AuthorizationStatus
from packages.schemas.capability import (
    Capability,
    CapabilitySet,
    buyer_agent_capabilities,
    payment_executor_capabilities,
    security_kernel_capabilities,
)
from services.payment_executor.executor import dispatch_create
from services.payment_executor.intents import create_payment_intent
from services.payment_executor.providers.base import ProviderPaymentMismatch
from services.payment_executor.providers.fake import FakePaymentProvider
from services.payment_executor.reconciliation import reconcile_intent
from services.security_kernel.authorization import load_authorization
from services.security_kernel.capability import CapabilityDenied, permits
from services.security_kernel.capability_registry import capabilities_for
from tests.conftest import authorized_mission


# --------------------------------------------------------------------------- #
# Separation of duties
# --------------------------------------------------------------------------- #
def test_only_the_payment_executor_principal_may_execute():
    """DENIED CAPABILITY -> PRIVILEGED EXECUTOR UNREACHABLE."""
    holders = [
        name
        for name in ("buyer-agent", "security-kernel", "payment-executor")
        if permits(capabilities_for(name), Capability.PAYMENT_EXECUTE)
    ]
    assert holders == ["payment-executor"]


def test_the_issuing_principal_cannot_spend():
    """Issuing and spending are different principals.

    This is the property that keeps a compromise of the authorization-minting
    path from becoming a compromise that moves money.
    """
    kernel = security_kernel_capabilities()
    executor = payment_executor_capabilities()

    assert permits(kernel, Capability.AUTHORIZATION_ISSUE)
    assert not permits(kernel, Capability.PAYMENT_EXECUTE)

    assert permits(executor, Capability.PAYMENT_EXECUTE)
    assert not permits(executor, Capability.AUTHORIZATION_ISSUE)


def test_the_executor_cannot_rewrite_the_rules_it_executes_under():
    executor = payment_executor_capabilities()
    for forbidden in (
        Capability.POLICY_MODIFY,
        Capability.MERCHANT_MODIFY,
        Capability.REFUND_EXECUTE,
    ):
        assert not permits(executor, forbidden)


def test_an_unknown_principal_is_denied_by_default():
    assert not permits(capabilities_for("attacker"), Capability.PAYMENT_EXECUTE)


# --------------------------------------------------------------------------- #
# The service refuses denied callers itself
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "capset_factory",
    [buyer_agent_capabilities, security_kernel_capabilities],
    ids=["buyer-agent", "security-kernel"],
)
async def test_denied_principal_cannot_create_a_payment_intent(session, capset_factory):
    """An LLM/agent tool call cannot bypass the service boundary."""
    mission, authorization, _ = await authorized_mission(session)

    with pytest.raises(CapabilityDenied) as exc:
        await create_payment_intent(
            session,
            capabilities=capset_factory(),
            mission_id=mission.id,
            authorization_id=authorization.authorization_id,
            idempotency_key="idem-denied",
            provider="fake",
        )
    assert exc.value.capability is Capability.PAYMENT_EXECUTE


async def test_a_forged_buyer_capability_set_is_re_resolved_from_trusted_policy(session):
    """An allow-list supplied by a caller is data, not authority.

    Phase 2 deliberately proves that a raw ``CapabilitySet`` can claim any
    permission.  A privileged Phase 4 boundary must therefore resolve the
    principal through the server-owned registry instead of trusting those
    caller-controlled allow/deny fields.
    """
    mission, authorization, _ = await authorized_mission(session)
    forged = CapabilitySet(
        principal="buyer-agent",
        allow={Capability.PAYMENT_EXECUTE},
    )

    with pytest.raises(CapabilityDenied):
        await create_payment_intent(
            session,
            capabilities=forged,
            mission_id=mission.id,
            authorization_id=authorization.authorization_id,
            idempotency_key="idem-forged-buyer",
            provider="fake",
        )

    refreshed = await load_authorization(session, authorization.authorization_id)
    assert refreshed.status == AuthorizationStatus.ACTIVE.value


async def test_a_denied_call_leaves_no_trace_at_all(session):
    """Enforcement runs FIRST, so a refused caller consumes nothing.

    A boundary that denies the operation but has already spent the
    authorization has not actually held.
    """
    mission, authorization, _ = await authorized_mission(session)

    with pytest.raises(CapabilityDenied):
        await create_payment_intent(
            session,
            capabilities=buyer_agent_capabilities(),
            mission_id=mission.id,
            authorization_id=authorization.authorization_id,
            idempotency_key="idem-no-trace",
            provider="fake",
        )

    refreshed = await load_authorization(session, authorization.authorization_id)
    assert refreshed is not None
    assert refreshed.status == AuthorizationStatus.ACTIVE.value
    assert refreshed.consumed_at is None

    from services.payment_executor.intents import find_by_idempotency_key

    assert await find_by_idempotency_key(session, "idem-no-trace") is None


async def test_denied_principal_cannot_dispatch_to_the_provider(session):
    """The provider call itself is gated, not only intent creation."""
    mission, authorization, _ = await authorized_mission(session)
    result = await create_payment_intent(
        session,
        capabilities=payment_executor_capabilities(),
        mission_id=mission.id,
        authorization_id=authorization.authorization_id,
        idempotency_key="idem-dispatch-denied",
        provider="fake",
    )
    from services.payment_executor.outbox import pending_events_for

    event = (await pending_events_for(session, result.intent.id))[0]
    provider = FakePaymentProvider()

    with pytest.raises(CapabilityDenied):
        await dispatch_create(
            session,
            capabilities=buyer_agent_capabilities(),
            provider=provider,
            intent=result.intent,
            event=event,
        )

    # The provider was never reached.
    assert provider.create_calls == []


async def test_worker_cannot_route_an_intent_to_a_different_provider(session):
    mission, authorization, _ = await authorized_mission(session)
    result = await create_payment_intent(
        session,
        capabilities=payment_executor_capabilities(),
        mission_id=mission.id,
        authorization_id=authorization.authorization_id,
        idempotency_key="idem-wrong-route",
        provider="fake",
    )
    from services.payment_executor.outbox import pending_events_for

    event = (await pending_events_for(session, result.intent.id))[0]
    provider = FakePaymentProvider()
    provider.name = "another-provider"

    with pytest.raises(ProviderPaymentMismatch):
        await dispatch_create(
            session,
            capabilities=payment_executor_capabilities(),
            provider=provider,
            intent=result.intent,
            event=event,
        )

    assert provider.get_calls == []
    assert provider.create_calls == []


async def test_denied_principal_cannot_reconcile(session):
    """Reconciliation can settle a payment, so it is gated identically."""
    mission, authorization, _ = await authorized_mission(session)
    result = await create_payment_intent(
        session,
        capabilities=payment_executor_capabilities(),
        mission_id=mission.id,
        authorization_id=authorization.authorization_id,
        idempotency_key="idem-reconcile-denied",
        provider="fake",
    )
    from services.payment_executor.outbox import pending_events_for

    event = (await pending_events_for(session, result.intent.id))[0]
    provider = FakePaymentProvider()

    with pytest.raises(CapabilityDenied):
        await reconcile_intent(
            session,
            capabilities=buyer_agent_capabilities(),
            provider=provider,
            intent=result.intent,
            event=event,
        )
    assert provider.get_calls == []


async def test_payment_cannot_be_requested_for_another_missions_authorization(session):
    """One mission's approval must not pay for another mission's basket."""
    _, authorization_a, _ = await authorized_mission(session)
    mission_b, _, _ = await authorized_mission(session, amount_inr=99999)

    from services.payment_executor.intents import PaymentRequestRejected

    with pytest.raises(PaymentRequestRejected):
        await create_payment_intent(
            session,
            capabilities=payment_executor_capabilities(),
            mission_id=mission_b.id,
            authorization_id=authorization_a.authorization_id,
            idempotency_key="idem-cross-mission",
            provider="fake",
        )


async def test_payment_requires_an_existing_authorization(session):
    """NO VALID AUTHORIZATION -> NO PAYMENT INTENT."""
    mission, _, _ = await authorized_mission(session)
    from services.security_kernel.authorization import AuthorizationNotFound

    with pytest.raises(AuthorizationNotFound):
        await create_payment_intent(
            session,
            capabilities=payment_executor_capabilities(),
            mission_id=mission.id,
            authorization_id=uuid.uuid4(),
            idempotency_key="idem-no-authorization",
            provider="fake",
        )


# --------------------------------------------------------------------------- #
# The same forgery, aimed at the ISSUING boundary
# --------------------------------------------------------------------------- #
async def test_a_forged_capability_set_cannot_mint_an_authorization(session):
    """LLM OUTPUT -> NEVER AUTHORIZATION, against a forged grant.

    ``payment.execute`` is not the only privileged capability, and a boundary
    that re-resolves the principal for spending while trusting a raw allow-list
    for *issuing* has moved the hole rather than closed it: an attacker who can
    mint an authorization does not need ``payment.execute``, because the
    executor will spend a valid one for it.

    The forged set names ``buyer-agent`` — the principal an LLM acts through —
    and simply asserts ``authorization.issue``, which the registry denies it.
    """
    from packages.schemas.transaction import BoundTransaction  # noqa: F401
    from services.security_kernel.authorization import (
        generate_nonce,
        issue_authorization,
    )
    from tests.conftest import FIXED_EXPIRY, approved_transaction, make_mission

    mission = await make_mission(session)
    forged = CapabilitySet(
        principal="buyer-agent",
        allow={Capability.AUTHORIZATION_ISSUE},
    )

    with pytest.raises(CapabilityDenied) as exc:
        await issue_authorization(
            session,
            capabilities=forged,
            mission_id=mission.id,
            transaction=approved_transaction(expires_at=FIXED_EXPIRY, nonce=generate_nonce()),
        )
    assert exc.value.capability is Capability.AUTHORIZATION_ISSUE

    # Enforcement precedes every write: no authorization row exists.
    from apps.api.db.models import AuthorizationRow
    from sqlalchemy import func, select

    count = await session.scalar(select(func.count()).select_from(AuthorizationRow))
    assert count == 0


async def test_a_forged_kernel_capability_set_is_also_refused(session):
    """Naming the RIGHT principal is not enough either.

    ``security-kernel`` genuinely holds ``authorization.issue``, so a set that
    names it and claims only that capability looks plausible. It is still
    refused, because the registry's set is compared whole: an attacker who can
    guess a principal name must not be able to hand-craft a *subset* of its
    grants and thereby strip the denials that travel with them.
    """
    from services.security_kernel.authorization import (
        generate_nonce,
        issue_authorization,
    )
    from tests.conftest import FIXED_EXPIRY, approved_transaction, make_mission

    mission = await make_mission(session)
    partial = CapabilitySet(
        principal="security-kernel",
        allow={Capability.AUTHORIZATION_ISSUE},
        # `deny` deliberately omitted — the real set denies payment.execute.
    )

    with pytest.raises(CapabilityDenied):
        await issue_authorization(
            session,
            capabilities=partial,
            mission_id=mission.id,
            transaction=approved_transaction(expires_at=FIXED_EXPIRY, nonce=generate_nonce()),
        )

    # The genuine registry set still works, so the guard is not simply broken.
    row = await issue_authorization(
        session,
        capabilities=security_kernel_capabilities(),
        mission_id=mission.id,
        transaction=approved_transaction(expires_at=FIXED_EXPIRY, nonce=generate_nonce()),
    )
    assert row.status == "PENDING"
