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
