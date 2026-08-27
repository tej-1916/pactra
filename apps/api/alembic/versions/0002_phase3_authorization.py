"""Phase 3 — transaction binding + authorization artifacts

Adds the `authorizations` table plus the version stamps that the transaction
digest binds to (`offers.offer_version`, `policy_decisions.policy_version`).

Uniqueness / integrity invariants introduced here:

    authorizations.nonce UNIQUE
    (status = 'CONSUMED') = (consumed_at IS NOT NULL)

Double-consumption is prevented by the atomic conditional UPDATE in
services/security_kernel/authorization.py (ACTIVE -> CONSUMED only while still
ACTIVE, unexpired, and digest-matched); these constraints make a duplicated
nonce and an inconsistent consumption record impossible at the storage layer.

Revision ID: 0002_phase3_authorization
Revises: 0001_initial
Create Date: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_phase3_authorization"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Version stamps bound into the transaction digest (spec section 7).
    with op.batch_alter_table("offers") as batch:
        batch.add_column(
            sa.Column("offer_version", sa.String(length=64), nullable=False, server_default="")
        )
    with op.batch_alter_table("policy_decisions") as batch:
        batch.add_column(
            sa.Column("policy_version", sa.String(length=40), nullable=False, server_default="")
        )

    op.create_table(
        "authorizations",
        sa.Column("authorization_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "mission_id",
            sa.Uuid(),
            sa.ForeignKey("missions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("transaction_digest", sa.String(length=64), nullable=False),
        sa.Column("nonce", sa.String(length=128), nullable=False),
        sa.Column("binding_version", sa.String(length=40), nullable=False),
        sa.Column("policy_version", sa.String(length=40), nullable=False),
        sa.Column("offer_version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("bound_merchant_id", sa.String(length=120), nullable=False),
        sa.Column("bound_product_id", sa.String(length=120), nullable=False),
        sa.Column("bound_quantity", sa.Integer(), nullable=False),
        sa.Column("bound_amount_inr", sa.Integer(), nullable=False),
        sa.Column("bound_currency", sa.String(length=3), nullable=False),
        # A nonce is used at most once system-wide.
        sa.UniqueConstraint("nonce", name="uq_authorizations_nonce"),
        # A consumption timestamp exists iff the artifact is consumed.
        sa.CheckConstraint(
            "(status = 'CONSUMED') = (consumed_at IS NOT NULL)",
            name="ck_authorizations_consumed_at_matches_status",
        ),
    )
    op.create_index("ix_authorizations_mission_id", "authorizations", ["mission_id"])
    op.create_index("ix_authorizations_status", "authorizations", ["status"])
    op.create_index(
        "ix_authorizations_transaction_digest", "authorizations", ["transaction_digest"]
    )


def downgrade() -> None:
    op.drop_index("ix_authorizations_transaction_digest", table_name="authorizations")
    op.drop_index("ix_authorizations_status", table_name="authorizations")
    op.drop_index("ix_authorizations_mission_id", table_name="authorizations")
    op.drop_table("authorizations")
    with op.batch_alter_table("policy_decisions") as batch:
        batch.drop_column("policy_version")
    with op.batch_alter_table("offers") as batch:
        batch.drop_column("offer_version")
