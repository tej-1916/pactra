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
