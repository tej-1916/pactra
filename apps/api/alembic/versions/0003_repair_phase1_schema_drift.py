"""repair Phase 1 schema drift (nullable mismatch)

ISOLATED REPAIR MIGRATION. It contains no Phase 4 objects on purpose: hiding a
pre-existing schema defect inside a feature migration makes the defect
invisible in the history, and makes the feature migration impossible to revert
without also reverting the repair.

WHAT WAS WRONG
--------------
`0001_initial_schema.py` declared several columns without `nullable=False`:

    missions.created_at            missions.updated_at
    mission_constraints.mission_id
    offers.mission_id
    policy_decisions.mission_id    policy_decisions.created_at
    audit_events.mission_id        audit_events.created_at

SQLAlchemy defaults a Column to nullable, and `sa.ForeignKey(...)` /
`server_default=sa.func.now()` do not change that. The ORM
(`apps/api/db/models.py`) declares the same columns as `Mapped[uuid.UUID]` and
`Mapped[datetime]` — i.e. NOT NULL. `alembic check` therefore reported eight
`modify_nullable` operations against a database migrated to head.

WHY IT MATTERS
--------------
It is not cosmetic. A NULL `audit_events.mission_id` would be an audit record
belonging to no mission — outside every per-mission hash chain and invisible to
per-mission verification. A NULL `offers.mission_id` or
`policy_decisions.mission_id` is an orphan security record. No code path
produces these today; nothing at the storage layer prevented them.

`0001_initial_schema.py` is deliberately NOT edited. Rewriting an applied
migration silently diverges every database that already ran it from the file
that claims to describe it.

SAFETY
------
This migration adds constraints and deletes nothing. If any row already holds a
NULL in one of these columns the ALTER fails loudly and the upgrade aborts —
which is the correct outcome. It must never "repair" by coercing an orphan row
to a fabricated value.

`batch_alter_table` is required for SQLite, which cannot ALTER a column in
place; on PostgreSQL it lowers to a plain `ALTER COLUMN ... SET NOT NULL`.

Revision ID: 0003_repair_phase1_drift
Revises: 0002_phase3_authorization
Create Date: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_repair_phase1_drift"
down_revision: str | None = "0002_phase3_authorization"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: (table, column, type) for every column that drifted. The type must be
#: restated because SQLite's batch mode rebuilds the table from this spec.
_DRIFTED: tuple[tuple[str, str, sa.types.TypeEngine], ...] = (
    ("missions", "created_at", sa.DateTime(timezone=True)),
    ("missions", "updated_at", sa.DateTime(timezone=True)),
    ("mission_constraints", "mission_id", sa.Uuid()),
    ("offers", "mission_id", sa.Uuid()),
    ("policy_decisions", "mission_id", sa.Uuid()),
    ("policy_decisions", "created_at", sa.DateTime(timezone=True)),
    ("audit_events", "mission_id", sa.Uuid()),
    ("audit_events", "created_at", sa.DateTime(timezone=True)),
)


def upgrade() -> None:
    for table, column, type_ in _DRIFTED:
        with op.batch_alter_table(table) as batch:
            batch.alter_column(column, existing_type=type_, nullable=False)


def downgrade() -> None:
    for table, column, type_ in _DRIFTED:
        with op.batch_alter_table(table) as batch:
            batch.alter_column(column, existing_type=type_, nullable=True)
