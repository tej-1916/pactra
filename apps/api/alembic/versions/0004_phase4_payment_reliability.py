"""Phase 4 — payment reliability (intents, outbox, webhooks)

Adds ONLY Phase 4 objects. The Phase 1 nullable drift is repaired separately in
0003_repair_phase1_drift so that neither change hides the other in the history.

Storage-level invariants introduced here, and what each one actually buys:

    payment_intents.idempotency_key      UNIQUE
        logical_payment_count(idempotency_key) <= 1, decided by the database
        rather than by an application check a race can slip past.

    payment_intents.authorization_id     UNIQUE
        an authorization is one-time, so it backs at most one logical payment.
        A SECOND, independent guard on "two concurrent requests cannot both
        consume one authorization" — the first is the Phase 3 conditional
        UPDATE in services/security_kernel/authorization.py.

    payment_intents.provider_payment_id  UNIQUE (NULLs not compared)
        one provider payment maps to at most one intent, so a mislinked
        reconciliation fails loudly instead of double-counting a charge.

    payment_intents.authorization_id     NOT NULL + FK ON DELETE RESTRICT
        NO VALID AUTHORIZATION -> NO PAYMENT INTENT, enforced by storage. There
        is no way to persist an intent that references no authorization, and an
        authorization backing a payment cannot be deleted out from under it.

    ck_payment_intents_succeeded_has_provider_id
        a SUCCEEDED payment must name the provider payment that succeeded. A
        success we cannot point at is one we cannot reconcile, refund or audit.

    webhook_events (provider, provider_event_id) UNIQUE
        repeated delivery of one provider event loses the INSERT race, so a
        webhook produces at most one state transition however often it arrives.

NOT enforced here, deliberately: column-level immutability of the bound
transaction data on payment_intents. That would require a database trigger,
which is not portable across PostgreSQL and SQLite. It is enforced in
application code and asserted by test, and is documented as such rather than
claimed as a database guarantee.

Revision ID: 0004_phase4_payment
Revises: 0003_repair_phase1_drift
Create Date: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_phase4_payment"
down_revision: str | None = "0003_repair_phase1_drift"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "payment_intents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "mission_id",
            sa.Uuid(),
            sa.ForeignKey("missions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # NOT NULL + FK: a payment intent without an authorization is
        # unrepresentable, not merely disallowed by convention.
        sa.Column(
            "authorization_id",
            sa.Uuid(),
            sa.ForeignKey("authorizations.authorization_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("transaction_digest", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("amount_inr", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("merchant_id", sa.String(length=120), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("provider_payment_id", sa.String(length=200), nullable=True),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_reason_code", sa.String(length=40), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_payment_intents_idempotency_key"),
        sa.UniqueConstraint("authorization_id", name="uq_payment_intents_authorization_id"),
        sa.UniqueConstraint("provider_payment_id", name="uq_payment_intents_provider_payment_id"),
        sa.CheckConstraint(
            "state <> 'SUCCEEDED' OR provider_payment_id IS NOT NULL",
            name="ck_payment_intents_succeeded_has_provider_id",
        ),
        sa.CheckConstraint("amount_inr >= 1", name="ck_payment_intents_amount_positive"),
        sa.CheckConstraint("attempts >= 0", name="ck_payment_intents_attempts_non_negative"),
    )
    op.create_index("ix_payment_intents_mission_id", "payment_intents", ["mission_id"])
    op.create_index("ix_payment_intents_state", "payment_intents", ["state"])

    op.create_table(
        "outbox_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "payment_intent_id",
            sa.Uuid(),
            sa.ForeignKey("payment_intents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="8"),
        # Both the retry schedule and the worker lease. A claim pushes it
        # forward, so a crashed worker's event becomes claimable again on its
        # own — crash recovery and backoff share one field by design.
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_by", sa.String(length=80), nullable=True),
        sa.Column("last_error", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("attempts >= 0", name="ck_outbox_attempts_non_negative"),
        sa.CheckConstraint("max_attempts >= 1", name="ck_outbox_max_attempts_positive"),
    )
    op.create_index("ix_outbox_events_payment_intent_id", "outbox_events", ["payment_intent_id"])
    op.create_index("ix_outbox_events_status", "outbox_events", ["status"])
    # The claim query orders by available_at; without this index every worker
    # turn is a full scan of the queue.
    op.create_index("ix_outbox_events_available_at", "outbox_events", ["available_at"])

    op.create_table(
        "webhook_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("provider_event_id", sa.String(length=200), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("provider_payment_id", sa.String(length=200), nullable=False),
        sa.Column(
            "payment_intent_id",
            sa.Uuid(),
            sa.ForeignKey("payment_intents.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("sequence", sa.Integer(), nullable=True),
        sa.Column(
            "received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_state", sa.String(length=24), nullable=True),
        # The deduplication mechanism for repeated delivery.
        sa.UniqueConstraint(
            "provider", "provider_event_id", name="uq_webhook_events_provider_event"
        ),
    )
    op.create_index("ix_webhook_events_payment_intent_id", "webhook_events", ["payment_intent_id"])


def downgrade() -> None:
    op.drop_index("ix_webhook_events_payment_intent_id", table_name="webhook_events")
    op.drop_table("webhook_events")
    op.drop_index("ix_outbox_events_available_at", table_name="outbox_events")
    op.drop_index("ix_outbox_events_status", table_name="outbox_events")
    op.drop_index("ix_outbox_events_payment_intent_id", table_name="outbox_events")
    op.drop_table("outbox_events")
    op.drop_index("ix_payment_intents_state", table_name="payment_intents")
    op.drop_index("ix_payment_intents_mission_id", table_name="payment_intents")
    op.drop_table("payment_intents")
