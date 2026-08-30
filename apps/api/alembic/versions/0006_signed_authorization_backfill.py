"""Explicitly classify historical authorization origins.

Rows backed by a persisted deterministic ALLOW decision become POLICY_AUTO.
Every other historical row becomes LEGACY_SERVER and therefore fails closed
in payment verification.  This never relabels an old REQUIRE_APPROVAL row as
user-approved.

Revision ID: 0006_signed_auth_backfill
Revises: 0005_signed_auth_expand
Create Date: 2026-08-29
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006_signed_auth_backfill"
down_revision: str | None = "0005_signed_auth_expand"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("UPDATE authorizations SET approval_scheme = 'LEGACY_SERVER'")
    op.execute(
        "UPDATE authorizations SET approval_scheme = 'POLICY_AUTO' "
        "WHERE EXISTS ("
        "SELECT 1 FROM policy_decisions "
        "WHERE policy_decisions.mission_id = authorizations.mission_id "
        "AND policy_decisions.policy_version = authorizations.policy_version "
        "AND policy_decisions.decision = 'ALLOW'"
        ")"
    )


def downgrade() -> None:
    op.execute("UPDATE authorizations SET approval_scheme = NULL")
