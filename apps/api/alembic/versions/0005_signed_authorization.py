"""Expand authorizations with nullable approval-proof columns.

Revision ID: 0005_signed_auth_expand
Revises: 0004_phase4_payment
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_signed_auth_expand"
down_revision: str | None = "0004_phase4_payment"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Expand first: nullable columns allow existing rows to survive the DDL.
    op.add_column("authorizations", sa.Column("approval_scheme", sa.String(24), nullable=True))
    op.add_column("authorizations", sa.Column("signing_key_id", sa.String(120), nullable=True))
    op.add_column("authorizations", sa.Column("approval_signature", sa.String(128), nullable=True))


def downgrade() -> None:
    op.drop_column("authorizations", "approval_signature")
    op.drop_column("authorizations", "signing_key_id")
    op.drop_column("authorizations", "approval_scheme")
