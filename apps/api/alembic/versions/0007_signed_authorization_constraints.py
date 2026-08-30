"""Enforce signed-authorization proof consistency.

Revision ID: 0007_signed_auth_constraints
Revises: 0006_signed_auth_backfill
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_signed_auth_constraints"
down_revision: str | None = "0006_signed_auth_backfill"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("authorizations") as batch:
        batch.alter_column("approval_scheme", existing_type=sa.String(24), nullable=False)
        batch.create_check_constraint(
            "ck_authorizations_approval_scheme_known",
            "approval_scheme IN ('POLICY_AUTO', 'USER_ED25519', 'LEGACY_SERVER')",
        )
        batch.create_check_constraint(
            "ck_authorizations_proof_pair_complete",
            "(signing_key_id IS NULL) = (approval_signature IS NULL)",
        )
        batch.create_check_constraint(
            "ck_authorizations_signature_shape",
            "approval_signature IS NULL OR "
            "(length(approval_signature) = 128 AND approval_signature = lower(approval_signature))",
        )
        batch.create_check_constraint(
            "ck_authorizations_scheme_proof_state",
            "(approval_scheme = 'POLICY_AUTO' AND signing_key_id IS NULL) OR "
            "(approval_scheme = 'LEGACY_SERVER' AND signing_key_id IS NULL) OR "
            "(approval_scheme = 'USER_ED25519' AND ("
            "(status = 'PENDING' AND signing_key_id IS NULL) OR "
            "(status IN ('ACTIVE', 'CONSUMED') AND signing_key_id IS NOT NULL) OR "
            "status IN ('EXPIRED', 'REVOKED'))) ",
        )


def downgrade() -> None:
    with op.batch_alter_table("authorizations") as batch:
        batch.drop_constraint("ck_authorizations_scheme_proof_state", type_="check")
        batch.drop_constraint("ck_authorizations_signature_shape", type_="check")
        batch.drop_constraint("ck_authorizations_proof_pair_complete", type_="check")
        batch.drop_constraint("ck_authorizations_approval_scheme_known", type_="check")
        batch.alter_column("approval_scheme", existing_type=sa.String(24), nullable=True)
