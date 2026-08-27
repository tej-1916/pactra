"""initial PACTRA schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "missions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("raw_query", sa.String(length=2000), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("state", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "mission_constraints",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "mission_id", sa.Uuid(), sa.ForeignKey("missions.id", ondelete="CASCADE"), unique=True
        ),
        sa.Column("category", sa.String(length=120), nullable=False),
        sa.Column("soft_budget_inr", sa.Integer(), nullable=False),
        sa.Column("hard_limit_inr", sa.Integer(), nullable=False),
        sa.Column("min_rating", sa.Float(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="INR"),
        sa.Column("allowed_merchants", sa.JSON(), nullable=True),
        sa.Column("blocked_merchants", sa.JSON(), nullable=False),
        sa.Column("min_merchant_trust", sa.Float(), nullable=False, server_default="0"),
    )

    op.create_table(
        "offers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("mission_id", sa.Uuid(), sa.ForeignKey("missions.id", ondelete="CASCADE")),
        sa.Column("merchant_id", sa.String(length=120), nullable=False),
        sa.Column("merchant_name", sa.String(length=200), nullable=False),
        sa.Column("merchant_trust", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("product_id", sa.String(length=120), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("amount_inr", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="INR"),
        sa.Column("rating", sa.Float(), nullable=False),
        sa.Column("in_stock", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("offered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("rejection_reasons", sa.JSON(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("raw", sa.JSON(), nullable=False),
    )

    op.create_table(
        "policy_decisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("mission_id", sa.Uuid(), sa.ForeignKey("missions.id", ondelete="CASCADE")),
        sa.Column("decision", sa.String(length=40), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("requested_amount", sa.Integer(), nullable=True),
        sa.Column("soft_budget", sa.Integer(), nullable=False),
        sa.Column("hard_limit", sa.Integer(), nullable=False),
        sa.Column("selected_offer_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "audit_events",
        sa.Column("event_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "mission_id", sa.Uuid(), sa.ForeignKey("missions.id", ondelete="CASCADE"), index=True
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("actor", sa.String(length=80), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("previous_hash", sa.String(length=64), nullable=False),
        sa.Column("event_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("mission_id", "sequence", name="uq_audit_mission_sequence"),
    )


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("policy_decisions")
    op.drop_table("offers")
    op.drop_table("mission_constraints")
    op.drop_table("missions")
