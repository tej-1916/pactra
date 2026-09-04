"""Persist monotonic provider ambiguity evidence.

Once multiple exact remote Orders have been observed for one logical payment,
later weaker search results cannot prove that the ambiguity disappeared. This
marker keeps that fact durable independently of ``last_reason_code``.

Revision ID: 0010_provider_ambiguity
Revises: 0009_razorpay_create_fence
Create Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_provider_ambiguity"
down_revision: str | None = "0009_razorpay_create_fence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("payment_intents") as batch:
        batch.add_column(
            sa.Column("provider_ambiguity_observed_at", sa.DateTime(timezone=True), nullable=True)
        )

    # Preserve ambiguity already recorded by the pre-marker implementation.
    op.execute(
        sa.text(
            """
            UPDATE payment_intents
            SET provider_ambiguity_observed_at = CURRENT_TIMESTAMP
            WHERE last_reason_code = 'PROVIDER_AMBIGUITY'
            """
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("payment_intents") as batch:
        batch.drop_column("provider_ambiguity_observed_at")
