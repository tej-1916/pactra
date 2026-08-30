"""Labelled SYNTHETIC scenarios for evaluating the risk engine.

EVERY LABEL HERE IS SYNTHETIC. SAID ONCE, PLAINLY.
---------------------------------------------------
There is no real fraud dataset in this project and none is claimed. These are
missions constructed from PACTRA's own domain models and driven through the REAL
kernel, then labelled BENIGN or RISKY by the author of the scenario. That makes
them a usable regression corpus and a defensible sanity check. It does NOT make
them evidence about real-world fraud, and no metric computed from them should
ever be described as a fraud-detection rate. ``EvaluationReport.data_disclosure``
carries this sentence into every report so it cannot be separated from the
numbers.

WHAT A LABEL MEANS HERE
-----------------------
``RISKY`` means *a reviewer would want to see this before money moved* — not
"an attack succeeded". Almost every RISKY scenario below is one the deterministic
kernel already REFUSED: a replay it blocked, a binding failure it caught, an
escalation the lattice denied. The risk engine's job is not to catch what the
kernel missed; it is to notice that this transaction is sitting in a mission
where those things happened. Labelling those RISKY is the honest reading of what
an advisory layer is for.

``BENIGN`` means the kernel permitted it and nothing about it warrants a human's
attention. A BENIGN case scoring at or above the review threshold is a FALSE
POSITIVE and is counted as one — that is the entire reason the benign half of
this corpus exists. Without it, a scorer that returned 1.0 unconditionally would
post a perfect detection rate.

THE LABELS ARE NOT DERIVED FROM THE SCORER
--------------------------------------------
Each scenario's label is written next to its construction, decided by what the
scenario BUILDS, and never read back from what the engine returned. There is no
code path in this module or in ``evaluation.py`` that adjusts a label to match a
score, and no threshold is fitted to make the numbers look better. That is the
difference between measuring a heuristic and grading its own homework.

REUSING THE ATTACK LAB
----------------------
Scenario isolation, the per-run in-memory database, the real-mission helpers,
and the hostile adapters (``SpoofingMerchant``, ``MismatchingProvider``) all come
from Phase 6. Nothing in Phase 6 is modified: its registry still holds exactly
its own scenarios, its block-rate semantics are untouched, and
``risk_detection_rate`` is computed here, separately, from a separate corpus.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, cast

from apps.api.db.models import AuditEventRow, Mission
from packages.schemas.approval import ApprovalScheme
from packages.schemas.capability import payment_executor_capabilities, security_kernel_capabilities
from packages.schemas.domain import (
    EventType,
    MissionConstraints,
    RawMerchantOffer,
)
from packages.schemas.merchant import MerchantRecord
from sqlalchemy import CursorResult, select, update

from services.agent_orchestrator.merchants.mock_merchants import (
    MockMerchantA,
    MockMerchantB,
    SpoofingMerchant,
)
from services.attack_lab.context import ScenarioContext
from services.attack_lab.scenarios._helpers import (
    constraints,
    drain_worker,
    worker_step,
)
from services.attack_lab.scenarios.adversaries import MismatchingProvider
from services.payment_executor.intents import create_payment_intent
from services.payment_executor.providers.fake import FakePaymentProvider, FaultMode
from services.security_kernel.authorization import (
    AuthorizationFailure,
    authorization_for_mission,
    consume_authorization,
    generate_nonce,
    issue_authorization,
    rebuild_bound_transaction,
)
from services.security_kernel.merchant_registry import MerchantRegistry

EXECUTOR = payment_executor_capabilities()
KERNEL = security_kernel_capabilities()

#: The standing disclosure. Copied verbatim into every evaluation report.
SYNTHETIC_DATA_DISCLOSURE = (
    "SYNTHETIC. These scenarios are constructed from PACTRA's own domain models "
    "and driven through the real kernel; their BENIGN/RISKY labels are authored, "
    "not observed. No real fraud data is used, and no metric computed from this "
    "corpus is a real-world fraud-detection rate."
)


class RiskLabel(str, Enum):
    """The authored ground truth for one scenario.

    Two values, not three. An "uncertain" label would be a place to hide every
    case the heuristic handles badly, and the point of the corpus is to have
    nowhere to hide them.
    """

    BENIGN = "BENIGN"
    RISKY = "RISKY"


class RiskCategory(str, Enum):
    """Grouping for per-category reporting, so a weakness is locatable."""

    BASELINE = "BASELINE"
    HIGH_VALUE = "HIGH_VALUE"
    COLD_START = "COLD_START"
    MERCHANT_TRUST = "MERCHANT_TRUST"
    SECURITY_HISTORY = "SECURITY_HISTORY"
    PAYMENT_ANOMALY = "PAYMENT_ANOMALY"
    AUDIT_INTEGRITY = "AUDIT_INTEGRITY"
    BEHAVIOURAL_ANOMALY = "BEHAVIOURAL_ANOMALY"


@dataclass(frozen=True)
class RiskCase:
    """What a scenario built: the mission to assess and the registry it used.

    The registry travels with the case because several scenarios register
    merchants the default table has never heard of. Assessing with the DEFAULT
    registry would then read trust 0.0 for a merchant the mission ran against at
    0.9, and the scenario would be measuring a fixture mismatch rather than the
    engine.
    """

    mission_id: uuid.UUID
    registry: MerchantRegistry
    #: Fixed instant for the assessment, so a scenario's score is reproducible
    #: across runs rather than drifting with authorization age.
    now: datetime


BuildFn = Callable[[ScenarioContext], Awaitable[RiskCase]]


@dataclass(frozen=True)
class RiskScenario:
    """One labelled case. The label is authored here and never revised."""

    id: str
    name: str
    label: RiskLabel
    category: RiskCategory
    description: str
    build: BuildFn


# --------------------------------------------------------------------------- #
# Merchant fixtures
# --------------------------------------------------------------------------- #
_FIXED_TS = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
#: Fixed assessment instant. Far enough after issuance that authorization age is
#: a stable small fraction of the window rather than a race against the clock.
ASSESS_AT = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


class HonestMerchant:
    """A well-behaved merchant agent. No injected text, no policy claims.

    Deliberately minimal: the benign half of the corpus must not accidentally
    carry a hostile signal. ``MockMerchantB`` cannot be used for a benign case
    because it ships an authority-escalation claim, and a "benign" scenario that
    attacks the policy register would make the false-positive rate meaningless.
    """

    def __init__(
        self,
        merchant_id: str,
        *,
        product_id: str = "hm-01",
        price: int = 2500,
        rating: float = 4.5,
    ) -> None:
        self.merchant_id = merchant_id
        self._product_id = product_id
        self._price = price
        self._rating = rating

    def quote(self, _constraints: MissionConstraints, _quantity: int) -> list[RawMerchantOffer]:
        return [
            RawMerchantOffer(
                merchant_id=self.merchant_id,
                product_id=self._product_id,
                title="Honest Earbuds",
                description="Plain product copy.",
                price=self._price,
                currency="INR",
                rating=self._rating,
                in_stock=True,
                offered_at=_FIXED_TS,
            )
        ]


def registry_with(**trust: float) -> MerchantRegistry:
    """A registry holding exactly the named merchants at the given trust.

    Built explicitly rather than mutating the default table. The default is
    module-level and process-wide; a scenario that edited it would leak into
    every scenario after it and into the rest of the test suite.
    """
    return MerchantRegistry(
        {
            merchant_id: MerchantRecord(
                merchant_id=merchant_id,
                display_name=merchant_id.replace("_", " ").title(),
                trust_score=score,
            )
            for merchant_id, score in trust.items()
        }
    )


#: The stock registry, restated locally so a scenario's expectations do not
#: silently change if the production table gains a merchant.
DEFAULT_TRUST = {"merchant_a": 0.9, "merchant_b": 0.75}


def default_registry() -> MerchantRegistry:
    return registry_with(**DEFAULT_TRUST)


# --------------------------------------------------------------------------- #
# Shared construction helpers
# --------------------------------------------------------------------------- #
async def _seed_merchant_history(
    context: ScenarioContext,
    *,
    merchant_id: str,
    amounts: list[int],
) -> None:
    """Give a merchant a prior authorization history.

    Built by CALLING ``issue_authorization`` under the kernel principal, on real
    missions — not by inserting rows. A baseline assembled from forged rows would
    let a scenario "demonstrate" an anomaly layer reading data the kernel never
    produced.
    """
    for index, amount in enumerate(amounts):
        async with context.sessionmaker() as session:
            mission = Mission(id=uuid.uuid4(), quantity=1, state="POLICY_CHECKED")
            session.add(mission)
            await session.flush()
            await issue_authorization(
                session,
                capabilities=KERNEL,
                mission_id=mission.id,
                transaction=context.bound_transaction(
                    merchant_id=merchant_id,
                    product_id=f"hist-{index}",
                    amount_inr=amount,
                    nonce=generate_nonce(),
                ),
                approval_scheme=ApprovalScheme.POLICY_AUTO,
            )
            await session.commit()


async def _consume_then_replay(context: ScenarioContext, mission_id: uuid.UUID) -> None:
    """Consume a mission's authorization, then present it again.

    The second consumption is refused by the kernel's atomic conditional UPDATE
    and writes ``AUTHORIZATION_REPLAY_DETECTED``. The scenario measures nothing
    about that refusal — Phase 6 already does — it just needs the resulting
    history to exist so the risk engine has something real to read.
    """
    async with context.sessionmaker() as session:
        row = await authorization_for_mission(session, mission_id)
        if row is None:  # pragma: no cover - scenario wiring
            raise RuntimeError(f"mission {mission_id} has no authorization to replay")
        transaction = rebuild_bound_transaction(row)
        authorization_id = row.authorization_id
        await consume_authorization(
            session, authorization_id=authorization_id, transaction=transaction, now=_FIXED_TS
        )
        await session.commit()

    async with context.sessionmaker() as session:
        try:
            await consume_authorization(
                session,
                authorization_id=authorization_id,
                transaction=transaction,
                now=_FIXED_TS,
            )
        except AuthorizationFailure:
            # Expected. The refusal is the point; the audit event is the artifact.
            pass
        await session.commit()


async def _approved_mission(
    context: ScenarioContext,
    *,
    merchants: list[Any],
    registry: MerchantRegistry,
    mission_constraints: MissionConstraints,
) -> uuid.UUID:
    """Run a real mission and cryptographically approve it if required.

    Uses ``Orchestrator`` through the Phase 6 helper, so every kernel stage runs.
    USER_ED25519 activation uses the evaluation harness's external demo signer;
    POLICY_AUTO is already activated by the orchestrator.
    """
    async with context.sessionmaker() as session:
        from packages.schemas.domain import CreateMissionRequest

        from services.agent_orchestrator.orchestrator import Orchestrator

        mission = await Orchestrator(merchants=merchants, registry=registry).run(
            session,
            CreateMissionRequest(quantity=1, constraints=mission_constraints),
        )
        mission_id = mission.id
        await session.commit()

    async with context.sessionmaker() as session:
        row = await authorization_for_mission(session, mission_id)
        if row is not None and row.status == "PENDING":
            await context.approve_pending_user_authorization(session, row)
            activated = await session.get(Mission, mission_id)
            if activated is not None:
                activated.state = "AUTHORIZED"
        await session.commit()
    return mission_id


async def _pay(
    context: ScenarioContext,
    mission_id: uuid.UUID,
    *,
    provider: Any,
    steps: int = 4,
) -> None:
    """Drive the real payment path for a mission, one worker step at a time.

    Stepping rather than draining: several handlers enqueue their own follow-up,
    and a drain would run the whole recovery before the scenario could leave the
    payment in the state it was trying to build.
    """
    async with context.sessionmaker() as session:
        row = await authorization_for_mission(session, mission_id)
        if row is None:  # pragma: no cover - scenario wiring
            raise RuntimeError(f"mission {mission_id} has no authorization to pay")
        await create_payment_intent(
            session,
            capabilities=EXECUTOR,
            mission_id=mission_id,
            authorization_id=row.authorization_id,
            idempotency_key=f"risk-eval-{mission_id}",
            provider=provider.name,
        )
        await session.commit()

    for _ in range(steps):
        if await worker_step(context, provider=provider) is None:
            break


# --------------------------------------------------------------------------- #
# BENIGN scenarios
# --------------------------------------------------------------------------- #
async def _build_benign_low_value(context: ScenarioContext) -> RiskCase:
    registry = default_registry()
    mission_id = await _approved_mission(
        context,
        merchants=[MockMerchantA()],
        registry=registry,
        mission_constraints=constraints(
            soft_budget_inr=20000, hard_limit_inr=25000, min_rating=3.5
        ),
    )
    return RiskCase(mission_id=mission_id, registry=registry, now=ASSESS_AT)


async def _build_benign_high_value_authorized(context: ScenarioContext) -> RiskCase:
    # 4299 against a 4500 ceiling: legitimately approved, legitimately close to
    # the limit. The case that must NOT be flagged, because an advisory layer
    # that flags every approved high-value purchase is an advisory layer nobody
    # will read.
    registry = default_registry()
    mission_id = await _approved_mission(
        context,
        merchants=[MockMerchantA()],
        registry=registry,
        mission_constraints=constraints(soft_budget_inr=4000, hard_limit_inr=4500, min_rating=3.5),
    )
    return RiskCase(mission_id=mission_id, registry=registry, now=ASSESS_AT)


async def _build_benign_cold_start(context: ScenarioContext) -> RiskCase:
    # A registered, well-trusted merchant with no prior transactions at all.
    # Must stay LOW: not knowing a counterparty's habits is not evidence against
    # them, and scoring it would make every first transaction suspicious.
    registry = registry_with(fresh_merchant=0.9)
    mission_id = await _approved_mission(
        context,
        merchants=[HonestMerchant("fresh_merchant", price=2400)],
        registry=registry,
        mission_constraints=constraints(
            soft_budget_inr=20000, hard_limit_inr=25000, min_rating=3.5
        ),
    )
    return RiskCase(mission_id=mission_id, registry=registry, now=ASSESS_AT)


async def _build_benign_established_merchant(context: ScenarioContext) -> RiskCase:
    registry = registry_with(steady_merchant=0.9)
    await _seed_merchant_history(
        context, merchant_id="steady_merchant", amounts=[2400, 2500, 2450, 2600, 2380, 2520]
    )
    mission_id = await _approved_mission(
        context,
        merchants=[HonestMerchant("steady_merchant", price=2500)],
        registry=registry,
        mission_constraints=constraints(
            soft_budget_inr=20000, hard_limit_inr=25000, min_rating=3.5
        ),
    )
    return RiskCase(mission_id=mission_id, registry=registry, now=ASSESS_AT)


async def _build_benign_moderate_trust(context: ScenarioContext) -> RiskCase:
    # Registry trust 0.75, just under the 0.80 advisory preference. Should cost
    # a token amount and stay LOW: a preference is not a policy.
    registry = default_registry()
    mission_id = await _approved_mission(
        context,
        merchants=[HonestMerchant("merchant_b", price=2600)],
        registry=registry,
        mission_constraints=constraints(
            soft_budget_inr=20000, hard_limit_inr=25000, min_rating=3.5
        ),
    )
    return RiskCase(mission_id=mission_id, registry=registry, now=ASSESS_AT)


async def _build_benign_competitive_selection(context: ScenarioContext) -> RiskCase:
    registry = default_registry()
    mission_id = await _approved_mission(
        context,
        merchants=[MockMerchantA(), HonestMerchant("merchant_b", price=2600, rating=4.4)],
        registry=registry,
        mission_constraints=constraints(
            soft_budget_inr=20000, hard_limit_inr=25000, min_rating=3.5
        ),
    )
    return RiskCase(mission_id=mission_id, registry=registry, now=ASSESS_AT)


async def _build_benign_settled_payment(context: ScenarioContext) -> RiskCase:
    # A payment that went through on the first attempt. One reconciliation-free,
    # timeout-free settlement must score nothing.
    registry = default_registry()
    mission_id = await _approved_mission(
        context,
        merchants=[MockMerchantA()],
        registry=registry,
        mission_constraints=constraints(
            soft_budget_inr=20000, hard_limit_inr=25000, min_rating=3.5
        ),
    )
    await _pay(context, mission_id, provider=FakePaymentProvider(), steps=3)
    return RiskCase(mission_id=mission_id, registry=registry, now=ASSESS_AT)


# --------------------------------------------------------------------------- #
# RISKY scenarios
# --------------------------------------------------------------------------- #
async def _build_risky_merchant_spoof_history(context: ScenarioContext) -> RiskCase:
    """A merchant that spoofed an identity on an EARLIER mission.

    Two missions. In the first, an agent authenticated as ``rogue_merchant``
    emits a payload claiming to be ``merchant_a``; the kernel rejects the offer
    and records MERCHANT_IDENTITY_MISMATCH naming the AUTHENTICATED id. In the
    second, the same merchant behaves impeccably. The transaction under
    assessment is the honest one — which is exactly the case an advisory layer
    exists for: nothing is wrong with this transaction, and something is very
    wrong with this counterparty.
    """
    registry = registry_with(rogue_merchant=0.9, merchant_a=0.9)
    await _approved_mission(
        context,
        merchants=[SpoofingMerchant(claimed_merchant_id="merchant_a"), MockMerchantA()],
        registry=MerchantRegistry(
            {
                **{
                    mid: MerchantRecord(merchant_id=mid, display_name=mid, trust_score=0.9)
                    for mid in ("rogue_merchant", "merchant_a")
                },
                "evil": MerchantRecord(merchant_id="evil", display_name="evil", trust_score=0.9),
            }
        ),
        mission_constraints=constraints(
            soft_budget_inr=20000, hard_limit_inr=25000, min_rating=3.5
        ),
    )
    # Re-attribute the recorded violation to the merchant under assessment. The
    # SpoofingMerchant fixture registers as "evil"; renaming the authenticated id
    # in the recorded event is how the scenario builds "this counterparty has a
    # history" without a second hostile adapter class.
    async with context.sessionmaker() as session:
        rows = (
            (
                await session.execute(
                    select(AuditEventRow).where(
                        AuditEventRow.event_type == EventType.SECURITY_VIOLATION.value
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            payload = dict(row.payload or {})
            if payload.get("authenticated_merchant_id") == "evil":
                payload["authenticated_merchant_id"] = "rogue_merchant"
                await session.execute(
                    update(AuditEventRow)
                    .where(AuditEventRow.event_id == row.event_id)
                    .values(payload=payload)
                )
        await session.commit()

    mission_id = await _approved_mission(
        context,
        merchants=[HonestMerchant("rogue_merchant", price=2500)],
        registry=registry,
        mission_constraints=constraints(
            soft_budget_inr=20000, hard_limit_inr=25000, min_rating=3.5
        ),
    )
    return RiskCase(mission_id=mission_id, registry=registry, now=ASSESS_AT)


async def _build_risky_authority_escalation(context: ScenarioContext) -> RiskCase:
    # MockMerchantB ships claims={"hard_limit_inr": 100000}. The lattice refuses
    # it and records a SECURITY_VIOLATION; the merchant is still the one this
    # mission transacts with.
    registry = default_registry()
    mission_id = await _approved_mission(
        context,
        merchants=[MockMerchantB()],
        registry=registry,
        mission_constraints=constraints(
            soft_budget_inr=20000, hard_limit_inr=25000, min_rating=3.5
        ),
    )
    return RiskCase(mission_id=mission_id, registry=registry, now=ASSESS_AT)


async def _build_risky_unknown_merchant(context: ScenarioContext) -> RiskCase:
    # Authenticated by the transport, absent from the registry: trust 0.0 and no
    # reputation of any kind. The user's own min_merchant_trust is 0.0 here, so
    # the deterministic policy permits it — which is precisely when advice helps.
    registry = registry_with(merchant_a=0.9)
    mission_id = await _approved_mission(
        context,
        merchants=[HonestMerchant("unregistered_merchant", price=2500)],
        registry=registry,
        mission_constraints=constraints(
            soft_budget_inr=20000, hard_limit_inr=25000, min_rating=3.5
        ),
    )
    return RiskCase(mission_id=mission_id, registry=registry, now=ASSESS_AT)


async def _build_risky_replay_attempt(context: ScenarioContext) -> RiskCase:
    registry = default_registry()
    mission_id = await _approved_mission(
        context,
        merchants=[MockMerchantA()],
        registry=registry,
        mission_constraints=constraints(
            soft_budget_inr=20000, hard_limit_inr=25000, min_rating=3.5
        ),
    )
    await _consume_then_replay(context, mission_id)
    return RiskCase(mission_id=mission_id, registry=registry, now=ASSESS_AT)


async def _build_risky_binding_failure(context: ScenarioContext) -> RiskCase:
    """A mutated transaction presented against a live authorization.

    The kernel refuses it with TRANSACTION_BINDING_FAILURE. Nothing here defeats
    the binding — the mutation is rejected exactly as Phase 3 requires — and the
    scenario only needs the refusal to be on the record.
    """
    registry = default_registry()
    mission_id = await _approved_mission(
        context,
        merchants=[MockMerchantA()],
        registry=registry,
        mission_constraints=constraints(
            soft_budget_inr=20000, hard_limit_inr=25000, min_rating=3.5
        ),
    )
    async with context.sessionmaker() as session:
        row = await authorization_for_mission(session, mission_id)
        if row is None:  # pragma: no cover - scenario wiring
            raise RuntimeError("no authorization to mutate")
        mutated = rebuild_bound_transaction(row).model_copy(update={"amount_inr": 9999})
        try:
            await consume_authorization(
                session,
                authorization_id=row.authorization_id,
                transaction=mutated,
                now=_FIXED_TS,
            )
        except AuthorizationFailure:
            pass
        await session.commit()
    return RiskCase(mission_id=mission_id, registry=registry, now=ASSESS_AT)


async def _build_risky_provider_mismatch(context: ScenarioContext) -> RiskCase:
    registry = default_registry()
    mission_id = await _approved_mission(
        context,
        merchants=[MockMerchantA()],
        registry=registry,
        mission_constraints=constraints(
            soft_budget_inr=20000, hard_limit_inr=25000, min_rating=3.5
        ),
    )
    # A 200 OK describing a different amount. The executor refuses to link or
    # settle and holds the intent uncertain, writing PROVIDER_RESPONSE_MISMATCH.
    provider = MismatchingProvider(override={"amount_inr": 1})
    context.provider = provider
    await _pay(context, mission_id, provider=provider, steps=2)
    return RiskCase(mission_id=mission_id, registry=registry, now=ASSESS_AT)


async def _build_risky_provider_timeouts(context: ScenarioContext) -> RiskCase:
    registry = default_registry()
    mission_id = await _approved_mission(
        context,
        merchants=[MockMerchantA()],
        registry=registry,
        mission_constraints=constraints(
            soft_budget_inr=20000, hard_limit_inr=25000, min_rating=3.5
        ),
    )
    provider = FakePaymentProvider()
    provider.queue_faults(
        FaultMode.TIMEOUT_BEFORE_CREATE,
        FaultMode.TIMEOUT_BEFORE_CREATE,
        FaultMode.TIMEOUT_BEFORE_CREATE,
    )
    context.provider = provider
    await _pay(context, mission_id, provider=provider, steps=6)
    await drain_worker(context, provider=provider, max_events=6)
    return RiskCase(mission_id=mission_id, registry=registry, now=ASSESS_AT)


async def _build_risky_amount_anomaly(context: ScenarioContext) -> RiskCase:
    """A transaction several times this merchant's historical median.

    Six prior authorizations around 1,000; this one at 4,299. Nothing about it
    breaks a rule — the deterministic engine permits it — so the anomaly layer is
    the only thing with anything to say.
    """
    registry = registry_with(quiet_merchant=0.9)
    await _seed_merchant_history(
        context, merchant_id="quiet_merchant", amounts=[950, 1000, 1050, 980, 1020, 1010]
    )
    mission_id = await _approved_mission(
        context,
        merchants=[HonestMerchant("quiet_merchant", price=4299)],
        registry=registry,
        mission_constraints=constraints(soft_budget_inr=4000, hard_limit_inr=4500, min_rating=3.5),
    )
    return RiskCase(mission_id=mission_id, registry=registry, now=ASSESS_AT)


async def _build_risky_tampered_audit_chain(context: ScenarioContext) -> RiskCase:
    """A mission whose hash chain no longer verifies.

    The payload of one event is edited directly in the database — what an
    attacker holding database access does, and what Phase 5's corruption tests
    already do. The risk engine is not the control here (``/audit/verify`` is);
    it should simply notice that every audit-derived feature it just read came
    from history that does not verify, and say so.
    """
    registry = default_registry()
    mission_id = await _approved_mission(
        context,
        merchants=[MockMerchantA()],
        registry=registry,
        mission_constraints=constraints(
            soft_budget_inr=20000, hard_limit_inr=25000, min_rating=3.5
        ),
    )
    async with context.sessionmaker() as session:
        row = (
            await session.execute(
                select(AuditEventRow)
                .where(AuditEventRow.mission_id == mission_id)
                .order_by(AuditEventRow.sequence.asc())
                .limit(1)
            )
        ).scalar_one()
        result = cast(
            CursorResult[Any],
            await session.execute(
                update(AuditEventRow)
                .where(AuditEventRow.event_id == row.event_id)
                .values(payload={**(row.payload or {}), "tampered": True})
            ),
        )
        # A tamper that touched nothing would leave the chain intact and the
        # scenario would silently measure the wrong thing — reporting the risk
        # engine as blind to an unverifiable chain when the chain was never
        # broken. Same guard Phase 6 added after exactly that bug.
        if result.rowcount != 1:  # pragma: no cover - defensive
            raise RuntimeError("audit tamper matched no row")
        await session.commit()
    return RiskCase(mission_id=mission_id, registry=registry, now=ASSESS_AT)


async def _build_risky_compound_security_history(context: ScenarioContext) -> RiskCase:
    """Two independent severe signals on one mission: replay AND binding failure.

    The case that should reach CRITICAL. Two unrelated attacks against the same
    transaction is the strongest thing this corpus contains, and if the scoring
    scale is calibrated as claimed, it is the case that saturates it.
    """
    registry = default_registry()
    mission_id = await _approved_mission(
        context,
        merchants=[MockMerchantA()],
        registry=registry,
        mission_constraints=constraints(soft_budget_inr=4000, hard_limit_inr=4500, min_rating=3.5),
    )
    async with context.sessionmaker() as session:
        row = await authorization_for_mission(session, mission_id)
        if row is None:  # pragma: no cover - scenario wiring
            raise RuntimeError("no authorization")
        transaction = rebuild_bound_transaction(row)
        authorization_id = row.authorization_id
        try:
            await consume_authorization(
                session,
                authorization_id=authorization_id,
                transaction=transaction.model_copy(update={"amount_inr": 4444}),
                now=_FIXED_TS,
            )
        except AuthorizationFailure:
            pass
        await session.commit()
    await _consume_then_replay(context, mission_id)
    return RiskCase(mission_id=mission_id, registry=registry, now=ASSESS_AT)


# --------------------------------------------------------------------------- #
# The corpus
# --------------------------------------------------------------------------- #
def _scenario(
    scenario_id: str,
    name: str,
    label: RiskLabel,
    category: RiskCategory,
    description: str,
    build: BuildFn,
) -> RiskScenario:
    return RiskScenario(
        id=scenario_id,
        name=name,
        label=label,
        category=category,
        description=description,
        build=build,
    )


#: Registration order is run order, so a batch is reproducible. Benign first, so
#: a text report reads as "what must not be flagged, then what must".
RISK_SCENARIOS: tuple[RiskScenario, ...] = (
    _scenario(
        "benign_low_value",
        "Low-value purchase well inside every limit",
        RiskLabel.BENIGN,
        RiskCategory.BASELINE,
        "A trusted registry merchant, an amount far below the ceiling, no history of anything.",
        _build_benign_low_value,
    ),
    _scenario(
        "benign_high_value_authorized",
        "High-value purchase, legitimately approved",
        RiskLabel.BENIGN,
        RiskCategory.HIGH_VALUE,
        "4,299 against a 4,500 ceiling from a 0.9-trust merchant: close to the "
        "limit and entirely legitimate. Must not be flagged.",
        _build_benign_high_value_authorized,
    ),
    _scenario(
        "benign_cold_start_merchant",
        "First transaction with a registered merchant",
        RiskLabel.BENIGN,
        RiskCategory.COLD_START,
        "No prior observations at all. Absence of history must contribute no risk.",
        _build_benign_cold_start,
    ),
    _scenario(
        "benign_established_merchant",
        "Typical purchase from a merchant with history",
        RiskLabel.BENIGN,
        RiskCategory.BEHAVIOURAL_ANOMALY,
        "Six prior authorizations around the same amount; this one is typical.",
        _build_benign_established_merchant,
    ),
    _scenario(
        "benign_moderate_trust_merchant",
        "Merchant just below the advisory trust preference",
        RiskLabel.BENIGN,
        RiskCategory.MERCHANT_TRUST,
        "Registry trust 0.75 against a 0.80 preference. A preference is not a policy.",
        _build_benign_moderate_trust,
    ),
    _scenario(
        "benign_competitive_selection",
        "Two honest merchants, best offer selected",
        RiskLabel.BENIGN,
        RiskCategory.BASELINE,
        "The ordinary multi-merchant path with nothing hostile in it.",
        _build_benign_competitive_selection,
    ),
    _scenario(
        "benign_settled_payment",
        "Payment settled on the first attempt",
        RiskLabel.BENIGN,
        RiskCategory.PAYMENT_ANOMALY,
        "One create, one success, no timeout and no reconciliation.",
        _build_benign_settled_payment,
    ),
    _scenario(
        "risky_merchant_spoof_history",
        "Counterparty has previously spoofed an identity",
        RiskLabel.RISKY,
        RiskCategory.SECURITY_HISTORY,
        "This transaction is honest; the merchant behind it asserted somebody "
        "else's identity on an earlier mission.",
        _build_risky_merchant_spoof_history,
    ),
    _scenario(
        "risky_authority_escalation",
        "Merchant attempted to rewrite the user's hard limit",
        RiskLabel.RISKY,
        RiskCategory.SECURITY_HISTORY,
        "The authority lattice refused the claim. The attempt is still the finding.",
        _build_risky_authority_escalation,
    ),
    _scenario(
        "risky_unknown_merchant",
        "Authenticated merchant absent from the registry",
        RiskLabel.RISKY,
        RiskCategory.MERCHANT_TRUST,
        "Zero reputation, and the user's own minimum-trust policy does not exclude it.",
        _build_risky_unknown_merchant,
    ),
    _scenario(
        "risky_replay_attempt",
        "A consumed authorization was presented again",
        RiskLabel.RISKY,
        RiskCategory.SECURITY_HISTORY,
        "Refused by the kernel's conditional UPDATE; the attempt is on the record.",
        _build_risky_replay_attempt,
    ),
    _scenario(
        "risky_binding_failure",
        "The transaction changed after approval",
        RiskLabel.RISKY,
        RiskCategory.SECURITY_HISTORY,
        "A mutated amount presented against a live authorization; digest mismatch.",
        _build_risky_binding_failure,
    ),
    _scenario(
        "risky_provider_mismatch",
        "Provider response described a different transaction",
        RiskLabel.RISKY,
        RiskCategory.PAYMENT_ANOMALY,
        "A 200 OK with the wrong amount. Nothing was linked and nothing settled.",
        _build_risky_provider_mismatch,
    ),
    _scenario(
        "risky_provider_timeouts",
        "Repeated provider timeouts left the payment uncertain",
        RiskLabel.RISKY,
        RiskCategory.PAYMENT_ANOMALY,
        "Several lost responses and the retries they forced.",
        _build_risky_provider_timeouts,
    ),
    _scenario(
        "risky_amount_anomaly",
        "Amount far above the merchant's historical median",
        RiskLabel.RISKY,
        RiskCategory.BEHAVIOURAL_ANOMALY,
        "Six prior authorizations around 1,000; this one at 4,299. No rule is broken.",
        _build_risky_amount_anomaly,
    ),
    _scenario(
        "risky_tampered_audit_chain",
        "The mission's audit chain does not verify",
        RiskLabel.RISKY,
        RiskCategory.AUDIT_INTEGRITY,
        "An event payload was edited directly in the database.",
        _build_risky_tampered_audit_chain,
    ),
    _scenario(
        "risky_compound_security_history",
        "Binding failure AND replay attempt on one mission",
        RiskLabel.RISKY,
        RiskCategory.SECURITY_HISTORY,
        "Two independent severe signals against the same transaction.",
        _build_risky_compound_security_history,
    ),
)

RISK_SCENARIOS_BY_ID: dict[str, RiskScenario] = {s.id: s for s in RISK_SCENARIOS}


def scenario_ids() -> list[str]:
    return [s.id for s in RISK_SCENARIOS]
