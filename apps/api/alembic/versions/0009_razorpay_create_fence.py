"""Durable one-way fence for non-idempotent provider creates.

``provider_create_fenced_at`` records only that PACTRA permanently consumed
permission to issue the first create operation for this logical payment.  It is
committed before provider I/O and therefore does not prove that a request ever
reached the provider.

Existing Razorpay intents are conservatively fenced when durable evidence says
an older worker may already have entered the create path.  In particular, an
outbox claim survives the crash window in which the remote Order was created
but every local handler write rolled back.

Revision ID: 0009_razorpay_create_fence
Revises: 0008_c2_razorpay
Create Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_razorpay_create_fence"
down_revision: str | None = "0008_c2_razorpay"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("payment_intents") as batch:
        batch.add_column(
            sa.Column("provider_create_fenced_at", sa.DateTime(timezone=True), nullable=True)
        )

    op.execute(
        sa.text(
            """
            UPDATE payment_intents
            SET provider_create_fenced_at = CURRENT_TIMESTAMP
            WHERE provider = 'razorpay_test'
              AND (
                    attempts > 0
                    OR provider_payment_id IS NOT NULL
                    OR EXISTS (
                        SELECT 1
                        FROM outbox_events
                        WHERE outbox_events.payment_intent_id = payment_intents.id
                          AND outbox_events.event_type = 'PAYMENT_CREATE_REQUESTED'
                          AND outbox_events.attempts > 0
                    )
              )
            """
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("payment_intents") as batch:
        batch.drop_column("provider_create_fenced_at")
