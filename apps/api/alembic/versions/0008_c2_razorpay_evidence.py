"""C2 Razorpay provider evidence

Persist the Razorpay Order identity separately from the eventual payment
identity and retain the safe reconciliation fields returned by the provider.
No C1 authorization, binding, digest, or audit schema is changed.

Revision ID: 0008_c2_razorpay
Revises: 0007_signed_auth_constraints
Create Date: 2026-08-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_c2_razorpay"
down_revision: str | None = "0007_signed_auth_constraints"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Batch mode is a no-op-style ALTER on PostgreSQL and a copy/move on
    # SQLite, whose ALTER TABLE cannot add named constraints directly.
    with op.batch_alter_table("payment_intents") as batch:
        batch.add_column(sa.Column("provider_order_id", sa.String(200)))
        batch.add_column(sa.Column("provider_transaction_id", sa.String(200)))
        batch.add_column(sa.Column("provider_receipt", sa.String(200)))
        batch.add_column(sa.Column("provider_status", sa.String(40)))
        batch.add_column(sa.Column("provider_attempts", sa.Integer()))
        batch.create_unique_constraint(
            "uq_payment_intents_provider_order_id", ["provider_order_id"]
        )
        batch.create_unique_constraint(
            "uq_payment_intents_provider_transaction_id", ["provider_transaction_id"]
        )
        batch.create_check_constraint(
            "ck_payment_intents_provider_attempts_non_negative",
            "provider_attempts IS NULL OR provider_attempts >= 0",
        )

    with op.batch_alter_table("webhook_events") as batch:
        batch.add_column(sa.Column("provider_transaction_id", sa.String(200)))


def downgrade() -> None:
    with op.batch_alter_table("webhook_events") as batch:
        batch.drop_column("provider_transaction_id")

    with op.batch_alter_table("payment_intents") as batch:
        batch.drop_constraint("ck_payment_intents_provider_attempts_non_negative", type_="check")
        batch.drop_constraint("uq_payment_intents_provider_transaction_id", type_="unique")
        batch.drop_constraint("uq_payment_intents_provider_order_id", type_="unique")
        batch.drop_column("provider_attempts")
        batch.drop_column("provider_status")
        batch.drop_column("provider_receipt")
        batch.drop_column("provider_transaction_id")
        batch.drop_column("provider_order_id")
