"""Per-scenario isolated execution context.

ATTACK ISOLATION IS A CORRECTNESS REQUIREMENT, NOT TIDINESS
-----------------------------------------------------------
If scenario 7 could observe rows scenario 6 left behind, then "the payment
intent count did not change" stops being evidence about scenario 7. Every
SQLite run therefore gets its OWN engine with its own freshly created schema,
disposed afterwards; every PostgreSQL run truncates the schema first. A result
is reproducible in the strong sense: running one scenario alone and running it
inside the full batch produce the same measurement.

WHAT THIS MODULE DELIBERATELY DOES NOT PROVIDE
----------------------------------------------
There is no ``disable_security`` switch, no "test mode" that relaxes a control,
and no back door into a kernel decision path. Attack scenarios construct hostile
INPUTS and call the real entry points; the only privilege this context grants is
the ability to create legitimate starting state (a mission, an authorization, a
settled payment) through the same kernel functions production uses, and the
ability to corrupt database rows DIRECTLY for the audit-tamper scenarios —
which is exactly what an attacker with database access would do, and is how the
Phase 5 corruption tests already prove tamper evidence.

The ``FakePaymentProvider`` is constructed per context rather than resolved
through ``services.payment_executor.registry.provider_for``, whose instance is
``lru_cache``d process-wide. A shared provider would carry payments between
scenarios and make "one provider payment exists for this key" meaningless.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from apps.api.db import models as _models  # noqa: F401  (register metadata)
from apps.api.db.base import Base
from apps.api.db.models import (
    AuditEventRow,
    AuthorizationRow,
    Mission,
    MissionConstraintsRow,
    Offer,
    OutboxEventRow,
    PaymentIntentRow,
    PolicyDecisionRow,
    WebhookEventRow,
)
from apps.api.db.session import configure_sqlite_transactions
from apps.api.pactra.config import get_settings
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from packages.schemas.approval import ApprovalScheme, approval_message
from packages.schemas.capability import security_kernel_capabilities
from packages.schemas.transaction import BoundTransaction
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from services.attack_lab.models import Backend
from services.payment_executor.providers.fake import FakePaymentProvider
from services.security_kernel.authorization import (
    activate_authorization,
    approve_authorization_with_signature,
    generate_nonce,
    issue_authorization,
)

#: A far-future expiry for scenarios that are not about expiry. Fixed rather
#: than relative so a digest computed in one scenario is reproducible.
FIXED_EXPIRY = datetime(2030, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

#: The reference "approved" transaction the Phase 3/4 suites already use, so an
#: attack-lab authorization is indistinguishable from a live one.
DEFAULT_AMOUNT_INR = 3799


def utc(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


@dataclass
class ScenarioContext:
    """Everything one scenario run is allowed to touch."""

    backend: Backend
    sessionmaker: async_sessionmaker[AsyncSession]
    #: A provider private to this run. Its ``created_payments`` map is the
    #: ground truth for "how many provider payments exist for this key".
    provider: FakePaymentProvider = field(default_factory=FakePaymentProvider)
    #: Scratch space for a scenario that needs to hand state from setup to
    #: execute without a return value. Never read by the runner.
    scratch: dict[str, Any] = field(default_factory=dict)
    #: External signer material owned by the authored test harness, never the
    #: API server or database. repr=False prevents accidental report/log output.
    _demo_approver_private_key: Ed25519PrivateKey = field(
        default_factory=Ed25519PrivateKey.generate,
        repr=False,
    )
    demo_approver_signing_key_id: str = "attack-harness-demo-user-ed25519-v1"

    def __post_init__(self) -> None:
        """Pre-enrol only the harness signer's public key in server config."""
        public_hex = (
            self._demo_approver_private_key.public_key()
            .public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
            .hex()
        )
        os.environ["DEMO_APPROVER_SIGNING_KEY_ID"] = self.demo_approver_signing_key_id
        os.environ["DEMO_APPROVER_PUBLIC_KEY_HEX"] = public_hex
        get_settings.cache_clear()

    async def approve_pending_user_authorization(
        self,
        session: AsyncSession,
        row: AuthorizationRow,
    ) -> AuthorizationRow:
        """Act as the external demo signer for an authored harness scenario."""
        message = approval_message(
            authorization_id=row.authorization_id,
            mission_id=row.mission_id,
            binding_version=row.binding_version,
            transaction_digest=row.transaction_digest,
            signing_key_id=self.demo_approver_signing_key_id,
        )
        return await approve_authorization_with_signature(
            session,
            mission_id=row.mission_id,
            authorization_id=row.authorization_id,
            signing_key_id=self.demo_approver_signing_key_id,
            signature_hex=self._demo_approver_private_key.sign(message).hex(),
        )

    def demo_approval_signature(self, row: AuthorizationRow) -> str:
        """Sign one challenge without exposing key material to a report."""
        message = approval_message(
            authorization_id=row.authorization_id,
            mission_id=row.mission_id,
            binding_version=row.binding_version,
            transaction_digest=row.transaction_digest,
            signing_key_id=self.demo_approver_signing_key_id,
        )
        return self._demo_approver_private_key.sign(message).hex()

    # ------------------------------------------------------------------ #
    # Row censuses — the evidence behind every "nothing happened" claim
    # ------------------------------------------------------------------ #
    async def _count(self, session: AsyncSession, model: Any) -> int:
        result = await session.execute(select(func.count()).select_from(model))
        return int(result.scalar_one())

    async def census(self) -> dict[str, int]:
        """Count every table an attack could plausibly move.

        Taken before and after each hostile action. "The attack was blocked" is
        only a claim; a census showing the payment-intent and provider-payment
        counts unchanged is the evidence for it.
        """
        async with self.sessionmaker() as session:
            return {
                "missions": await self._count(session, Mission),
                "mission_constraints": await self._count(session, MissionConstraintsRow),
                "offers": await self._count(session, Offer),
                "policy_decisions": await self._count(session, PolicyDecisionRow),
                "authorizations": await self._count(session, AuthorizationRow),
                "payment_intents": await self._count(session, PaymentIntentRow),
                "outbox_events": await self._count(session, OutboxEventRow),
                "webhook_events": await self._count(session, WebhookEventRow),
                "audit_events": await self._count(session, AuditEventRow),
                "provider_payments": len(self.provider.created_payments),
            }

    async def payment_intent_count(self) -> int:
        async with self.sessionmaker() as session:
            return await self._count(session, PaymentIntentRow)

    def provider_payment_count(self, idempotency_key: str) -> int:
        return self.provider.payment_count_for(idempotency_key)

    # ------------------------------------------------------------------ #
    # Legitimate starting state, built through the REAL kernel
    # ------------------------------------------------------------------ #
    async def make_mission(self, state: str = "POLICY_CHECKED") -> uuid.UUID:
        async with self.sessionmaker() as session:
            mission = Mission(id=uuid.uuid4(), quantity=1, state=state)
            session.add(mission)
            await session.commit()
            return mission.id

    def bound_transaction(self, **overrides: Any) -> BoundTransaction:
        base: dict[str, Any] = dict(
            merchant_id="merchant_a",
            product_id="P1",
            quantity=1,
            amount_inr=DEFAULT_AMOUNT_INR,
            currency="INR",
            policy_version="policy-v1",
            offer_version="offer-v1",
            expires_at=FIXED_EXPIRY,
            nonce=generate_nonce(),
        )
        base.update(overrides)
        return BoundTransaction(**base)

    async def authorized_mission(
        self,
        *,
        amount_inr: int = DEFAULT_AMOUNT_INR,
        expires_at: datetime | None = None,
        activate: bool = True,
        **overrides: Any,
    ) -> tuple[uuid.UUID, uuid.UUID, BoundTransaction]:
        """A mission in AUTHORIZED holding an ACTIVE authorization.

        Built by CALLING ``issue_authorization`` and ``activate_authorization``
        — the kernel's own path, under the ``security-kernel`` principal — not
        by inserting a row with ``status='ACTIVE'``. An authorization forged by
        direct INSERT would let a scenario "prove" a control that never ran.

        Returns ``(mission_id, authorization_id, bound_transaction)``.
        """
        mission_id = await self.make_mission("POLICY_CHECKED")
        transaction = self.bound_transaction(
            amount_inr=amount_inr,
            expires_at=expires_at or FIXED_EXPIRY,
            **overrides,
        )
        async with self.sessionmaker() as session:
            session.add(
                PolicyDecisionRow(
                    mission_id=mission_id,
                    decision="ALLOW",
                    policy_version=transaction.policy_version,
                    reason_codes=["WITHIN_LIMITS"],
                    requested_amount=transaction.amount_inr,
                    soft_budget=transaction.amount_inr,
                    hard_limit=transaction.amount_inr,
                    selected_offer_id=None,
                )
            )
            await session.flush()
            row = await issue_authorization(
                session,
                capabilities=security_kernel_capabilities(),
                mission_id=mission_id,
                transaction=transaction,
                approval_scheme=ApprovalScheme.POLICY_AUTO,
            )
            authorization_id = row.authorization_id
            if activate:
                await activate_authorization(session, authorization_id=authorization_id)
                mission = await session.get(Mission, mission_id)
                assert mission is not None  # noqa: S101 - fixture wiring, not a control
                mission.state = "AUTHORIZED"
            await session.commit()
        return mission_id, authorization_id, transaction

    async def expired_authorization(
        self, *, ttl: timedelta = timedelta(minutes=15)
    ) -> tuple[uuid.UUID, uuid.UUID, BoundTransaction, datetime]:
        """An ACTIVE authorization whose window has since closed.

        Issued with a real future expiry and activated normally; the ATTACK then
        presents it at a moment past ``expires_at``. Nothing rewrites the row to
        look expired — the kernel's ``expires_at > :now`` predicate is what has
        to refuse it, so the clock is what moves, not the data.
        """
        issued_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        expires_at = issued_at + ttl
        mission_id = await self.make_mission("POLICY_CHECKED")
        transaction = self.bound_transaction(expires_at=expires_at)
        async with self.sessionmaker() as session:
            session.add(
                PolicyDecisionRow(
                    mission_id=mission_id,
                    decision="ALLOW",
                    policy_version=transaction.policy_version,
                    reason_codes=["WITHIN_LIMITS"],
                    requested_amount=transaction.amount_inr,
                    soft_budget=transaction.amount_inr,
                    hard_limit=transaction.amount_inr,
                    selected_offer_id=None,
                )
            )
            await session.flush()
            row = await issue_authorization(
                session,
                capabilities=security_kernel_capabilities(),
                mission_id=mission_id,
                transaction=transaction,
                approval_scheme=ApprovalScheme.POLICY_AUTO,
                issued_at=issued_at,
            )
            authorization_id = row.authorization_id
            await activate_authorization(session, authorization_id=authorization_id, now=issued_at)
            mission = await session.get(Mission, mission_id)
            assert mission is not None  # noqa: S101 - fixture wiring, not a control
            mission.state = "AUTHORIZED"
            await session.commit()
        return mission_id, authorization_id, transaction, expires_at + timedelta(seconds=1)


# --------------------------------------------------------------------------- #
# Backend provisioning
# --------------------------------------------------------------------------- #
async def make_sqlite_context() -> tuple[ScenarioContext, AsyncEngine]:
    """A private in-memory database with the full schema.

    ``configure_sqlite_transactions`` is not optional: without it the sqlite3
    driver manages transactions itself, ROLLBACK becomes a no-op and SAVEPOINT
    stops isolating — so the atomicity an attack is trying to break would not
    exist to break. See ``apps/api/db/session.py``.
    """
    engine = configure_sqlite_transactions(
        create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    return ScenarioContext(backend=Backend.SQLITE, sessionmaker=maker), engine


class PostgresUnavailable(Exception):
    """No PostgreSQL server was reachable.

    Raised so the runner can report INCONCLUSIVE. A concurrency guarantee that
    was not exercised must never be reported as one that was.
    """


#: The same server the Phase 4/5 PostgreSQL suite uses, and the same override
#: variable. Resolved here rather than imported from ``tests.pg`` because
#: ``services`` is an installed package and ``tests`` is not — a service module
#: importing the test package works from a source checkout and fails everywhere
#: else, which is the worst possible place to discover a layering mistake.
DEFAULT_POSTGRES_URL = "postgresql+asyncpg://pactra:pactra@localhost:5432/pactra_test"


def postgres_url() -> str:
    return os.environ.get("PACTRA_TEST_DATABASE_URL", DEFAULT_POSTGRES_URL)


def postgres_target() -> str:
    """Host/database, for a skip message. Never the credentials."""
    return postgres_url().rsplit("@", 1)[-1]


async def _ensure_database(url: str) -> bool:
    """Create the target database if absent. False if the server is unreachable."""
    admin_url = url.rsplit("/", 1)[0] + "/postgres"
    target = url.rsplit("/", 1)[-1]
    engine = create_async_engine(
        admin_url, future=True, poolclass=NullPool, isolation_level="AUTOCOMMIT"
    )
    try:
        async with engine.connect() as connection:
            exists = await connection.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": target}
            )
            if not exists:
                await connection.execute(text(f'CREATE DATABASE "{target}"'))
        return True
    except Exception:
        return False
    finally:
        await engine.dispose()


#: Truncated between scenario runs, ordered so CASCADE has nothing to chase.
_TRUNCATE_ORDER = (
    "webhook_events",
    "outbox_events",
    "payment_intents",
    "authorizations",
    "audit_events",
    "policy_decisions",
    "offers",
    "mission_constraints",
    "missions",
)


async def make_postgres_engine() -> AsyncEngine:
    """One engine for the whole batch, with connection-level concurrency.

    ``NullPool`` is not a tuning choice: with a pooled engine two "concurrent"
    sessions can be handed the same connection, and a race that cannot happen is
    not a race that was tested.
    """
    url = postgres_url()
    if not await _ensure_database(url):
        raise PostgresUnavailable(postgres_target())

    engine = create_async_engine(url, future=True, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    except Exception as exc:  # pragma: no cover - server vanished mid-setup
        await engine.dispose()
        raise PostgresUnavailable(str(exc)) from exc
    return engine


async def make_postgres_context(engine: AsyncEngine) -> ScenarioContext:
    """Reset the shared PostgreSQL schema and hand back a clean context.

    TRUNCATE rather than DROP/CREATE: the schema is built once per batch, so
    each scenario pays for row removal instead of DDL.
    """
    async with engine.begin() as connection:
        await connection.execute(
            text(f"TRUNCATE {', '.join(_TRUNCATE_ORDER)} RESTART IDENTITY CASCADE")
        )
    maker = async_sessionmaker(engine, expire_on_commit=False)
    return ScenarioContext(backend=Backend.POSTGRES, sessionmaker=maker)
