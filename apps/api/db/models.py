"""SQLAlchemy 2 ORM models.

Uses dialect-neutral column types (Uuid, JSON, timezone-aware DateTime) so the
same schema/migration runs on PostgreSQL (runtime) and SQLite (tests).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.db.base import Base


class Mission(Base):
    __tablename__ = "missions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    raw_query: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    state: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    constraints: Mapped[MissionConstraintsRow] = relationship(
        back_populates="mission", uselist=False, cascade="all, delete-orphan"
    )
    offers: Mapped[list[Offer]] = relationship(
        back_populates="mission", cascade="all, delete-orphan"
    )
    policy_decisions: Mapped[list[PolicyDecisionRow]] = relationship(
        back_populates="mission", cascade="all, delete-orphan"
    )
    audit_events: Mapped[list[AuditEventRow]] = relationship(
        back_populates="mission", cascade="all, delete-orphan"
    )
    authorizations: Mapped[list[AuthorizationRow]] = relationship(
        back_populates="mission", cascade="all, delete-orphan"
    )
    payment_intents: Mapped[list[PaymentIntentRow]] = relationship(
        back_populates="mission", cascade="all, delete-orphan"
    )


class MissionConstraintsRow(Base):
    __tablename__ = "mission_constraints"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    mission_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("missions.id", ondelete="CASCADE"), unique=True
    )
    category: Mapped[str] = mapped_column(String(120))
    soft_budget_inr: Mapped[int] = mapped_column(Integer)
    hard_limit_inr: Mapped[int] = mapped_column(Integer)
    min_rating: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    allowed_merchants: Mapped[list | None] = mapped_column(JSON, nullable=True)
    blocked_merchants: Mapped[list] = mapped_column(JSON, default=list)
    min_merchant_trust: Mapped[float] = mapped_column(Float, default=0.0)

    mission: Mapped[Mission] = relationship(back_populates="constraints")


class Offer(Base):
    __tablename__ = "offers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    mission_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("missions.id", ondelete="CASCADE")
    )
    offer_version: Mapped[str] = mapped_column(String(64), default="")
    merchant_id: Mapped[str] = mapped_column(String(120))
    merchant_name: Mapped[str] = mapped_column(String(200))
    merchant_trust: Mapped[float] = mapped_column(Float, default=0.5)
    product_id: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(300))
    amount_inr: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    rating: Mapped[float] = mapped_column(Float)
    in_stock: Mapped[bool] = mapped_column(Boolean, default=True)
    offered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid: Mapped[bool] = mapped_column(Boolean, default=True)
    rejection_reasons: Mapped[list] = mapped_column(JSON, default=list)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw: Mapped[dict] = mapped_column(JSON, default=dict)

    mission: Mapped[Mission] = relationship(back_populates="offers")


class PolicyDecisionRow(Base):
    __tablename__ = "policy_decisions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    mission_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("missions.id", ondelete="CASCADE")
    )
    decision: Mapped[str] = mapped_column(String(40))
    policy_version: Mapped[str] = mapped_column(String(40), default="")
    reason_codes: Mapped[list] = mapped_column(JSON, default=list)
    requested_amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    soft_budget: Mapped[int] = mapped_column(Integer)
    hard_limit: Mapped[int] = mapped_column(Integer)
    selected_offer_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    mission: Mapped[Mission] = relationship(back_populates="policy_decisions")


class AuditEventRow(Base):
    __tablename__ = "audit_events"
    __table_args__ = (UniqueConstraint("mission_id", "sequence", name="uq_audit_mission_sequence"),)

    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    mission_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("missions.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(40))
    actor: Mapped[str] = mapped_column(String(80))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    previous_hash: Mapped[str] = mapped_column(String(64))
    event_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    mission: Mapped[Mission] = relationship(back_populates="audit_events")


class AuthorizationRow(Base):
    """Persisted authorization artifact (Phase 3).

    Two database-level guarantees live here:

    * ``uq_authorizations_nonce`` — a nonce is used at most once system-wide, so
      an authorization can never be duplicated by re-minting the same nonce.
    * ``ck_authorizations_consumed_at_matches_status`` — a consumption timestamp
      exists if and only if the row is CONSUMED, so no code path can mark an
      authorization consumed without recording when, or stamp a consumption
      time onto a still-usable authorization.

    The protection against DOUBLE consumption is not this CHECK: it is the
    single atomic conditional UPDATE in
    ``services.security_kernel.authorization.consume_authorization``, which
    transitions ACTIVE -> CONSUMED only if the row is still ACTIVE, still
    unexpired, and still bound to the presented digest. The database decides via
    ``rowcount``; no in-memory flag participates.

    The ``bound_*`` columns record the exact transaction the digest commits to.
    They are stored for audit and for independent re-derivation of the digest —
    the digest itself remains the enforcement mechanism.
    """

    __tablename__ = "authorizations"
    __table_args__ = (
        UniqueConstraint("nonce", name="uq_authorizations_nonce"),
        CheckConstraint(
            "(status = 'CONSUMED') = (consumed_at IS NOT NULL)",
            name="ck_authorizations_consumed_at_matches_status",
        ),
    )

    authorization_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    mission_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("missions.id", ondelete="CASCADE"), index=True
    )
    transaction_digest: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # Server-held entropy. NEVER returned by the API and never written into an
    # audit payload.
    nonce: Mapped[str] = mapped_column(String(128), nullable=False)
    binding_version: Mapped[str] = mapped_column(String(40), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(40), nullable=False)
    offer_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The exact bound transaction, for audit and digest re-derivation.
    bound_merchant_id: Mapped[str] = mapped_column(String(120), nullable=False)
    bound_product_id: Mapped[str] = mapped_column(String(120), nullable=False)
    bound_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    bound_amount_inr: Mapped[int] = mapped_column(Integer, nullable=False)
    bound_currency: Mapped[str] = mapped_column(String(3), nullable=False)

    mission: Mapped[Mission] = relationship(back_populates="authorizations")


class PaymentIntentRow(Base):
    """One LOGICAL payment (Phase 4).

    Storage-level invariants, in the order they matter:

    * ``uq_payment_intents_idempotency_key`` — this is the whole idempotency
      guarantee. ``logical_payment_count(idempotency_key) <= 1`` is enforced by
      the database, not by an application check that a race can slip past.
    * ``uq_payment_intents_authorization_id`` — an authorization is one-time, so
      it can back at most one logical payment. This is a SECOND, independent
      guard on "two concurrent requests cannot both consume one authorization":
      even if the Phase 3 conditional UPDATE were somehow defeated, storage
      still refuses the second intent.
    * ``uq_payment_intents_provider_payment_id`` — one provider payment maps to
      at most one intent, so a reconciliation that mislinked a provider payment
      to a second intent fails loudly instead of double-counting a charge.
      NULLs are not compared by either PostgreSQL or SQLite, so any number of
      intents may sit un-linked.
    * ``ck_payment_intents_succeeded_has_provider_id`` — a SUCCEEDED payment
      must name the provider payment that succeeded. A success we cannot point
      at is not a success we can reconcile, refund, or audit.

    ``authorization_id`` is NOT NULL with a foreign key: authorization linkage
    is structural. There is no way to persist a payment intent that references
    no authorization — NO VALID AUTHORIZATION -> NO PAYMENT INTENT holds at the
    storage layer, not only in the service.

    The ``transaction_digest`` and the ``amount_inr``/``currency``/
    ``merchant_id`` triple are copied from the authorization at creation time
    and are never written again by any code path. True column-level
    immutability would require a database trigger, which is not portable across
    PostgreSQL and SQLite; this is enforced in application code and asserted by
    test rather than claimed as a database guarantee.
    """

    __tablename__ = "payment_intents"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_payment_intents_idempotency_key"),
        UniqueConstraint("authorization_id", name="uq_payment_intents_authorization_id"),
        UniqueConstraint("provider_payment_id", name="uq_payment_intents_provider_payment_id"),
        CheckConstraint(
            "state <> 'SUCCEEDED' OR provider_payment_id IS NOT NULL",
            name="ck_payment_intents_succeeded_has_provider_id",
        ),
        CheckConstraint("amount_inr >= 1", name="ck_payment_intents_amount_positive"),
        CheckConstraint("attempts >= 0", name="ck_payment_intents_attempts_non_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    mission_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("missions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    authorization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("authorizations.authorization_id", ondelete="RESTRICT"),
        nullable=False,
    )
    # Copied from the authorization; the executor re-derives and re-checks it.
    transaction_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    # Commitment to every field that makes two requests "the same request".
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    amount_inr: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    merchant_id: Mapped[str] = mapped_column(String(120), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_payment_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    state: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_reason_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    mission: Mapped[Mission] = relationship(back_populates="payment_intents")
    outbox_events: Mapped[list[OutboxEventRow]] = relationship(
        back_populates="payment_intent", cascade="all, delete-orphan"
    )


class OutboxEventRow(Base):
    """Transactional outbox (Phase 4).

    An outbox row is written in the SAME database transaction as the payment
    intent it describes. That is the entire reason this table exists: the
    provider is only ever called from a row that is already durable, so a crash
    between "decided to pay" and "called the provider" leaves a record that a
    worker will pick up, rather than an intent nobody will ever act on.

    ``available_at`` is both the retry schedule and the worker lease. Claiming
    pushes it forward by a lease interval, so an event whose worker died is
    reclaimable once the lease lapses — crash recovery falls out of the same
    mechanism as backoff instead of needing a second one.
    """

    __tablename__ = "outbox_events"
    __table_args__ = (
        CheckConstraint("attempts >= 0", name="ck_outbox_attempts_non_negative"),
        CheckConstraint("max_attempts >= 1", name="ck_outbox_max_attempts_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    payment_intent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("payment_intents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=8)
    # Next moment this event may be claimed. Doubles as the worker lease.
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    claimed_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    payment_intent: Mapped[PaymentIntentRow] = relationship(back_populates="outbox_events")


class WebhookEventRow(Base):
    """Record of a provider webhook, for idempotent handling (Phase 4).

    ``uq_webhook_events_provider_event`` is the deduplication mechanism. A
    repeated delivery of the same provider event loses the INSERT race and is
    ignored, so a webhook can be delivered any number of times without
    producing a second state transition or a second side effect.

    Only VERIFIED webhooks are recorded with a payment linkage. A rejected
    signature is audited, never persisted here as if it were an event — an
    unverified payload must not be able to occupy a provider_event_id and
    thereby suppress the genuine delivery that follows.
    """

    __tablename__ = "webhook_events"
    __table_args__ = (
        UniqueConstraint("provider", "provider_event_id", name="uq_webhook_events_provider_event"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(200), nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_payment_id: Mapped[str] = mapped_column(String(200), nullable=False)
    payment_intent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("payment_intents.id", ondelete="CASCADE"), nullable=True, index=True
    )
    sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_state: Mapped[str | None] = mapped_column(String(24), nullable=True)
