"""Authorization artifact and lifecycle.

An artifact is either a deterministic ``POLICY_AUTO`` authorization or a
``USER_ED25519`` LOCAL CRYPTOGRAPHIC APPROVAL PROOF made with the pre-enrolled
DEMO USER-CONTROLLED SIGNING KEY.  This is not production identity and is not
described as non-repudiation.

Status model
------------
```text
PENDING  --activate-->  ACTIVE  --consume-->  CONSUMED   (terminal)
   |                       |
   +-----------------------+--expire--> EXPIRED          (terminal)
   +-----------------------+--revoke--> REVOKED          (terminal)
```
Only ``ACTIVE`` is consumable, and consumption is one-time.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.schemas.approval import SIGNATURE_HEX_LENGTH, ApprovalScheme
from packages.schemas.invariants import require
from packages.schemas.transaction import BINDING_VERSION

DIGEST_HEX_LENGTH = 64


class AuthorizationStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


#: Statuses from which no further transition is possible.
TERMINAL_STATUSES = frozenset(
    {
        AuthorizationStatus.CONSUMED,
        AuthorizationStatus.EXPIRED,
        AuthorizationStatus.REVOKED,
    }
)


class Authorization(BaseModel):
    """In-memory projection of an authorization row.

    The persisted row (``apps.api.db.models.AuthorizationRow``) is the source of
    truth for the lifecycle; this model is what the kernel reasons over and what
    tests assert against. It deliberately carries the ``nonce`` because the
    kernel needs it to recompute the digest — the API projection does not.
    """

    model_config = ConfigDict(extra="forbid")

    authorization_id: uuid.UUID
    mission_id: uuid.UUID
    transaction_digest: str = Field(
        min_length=DIGEST_HEX_LENGTH,
        max_length=DIGEST_HEX_LENGTH,
        pattern=r"^[0-9a-f]+$",
    )
    nonce: str = Field(min_length=64, max_length=128, pattern=r"^[0-9a-f]+$")
    issued_at: datetime
    expires_at: datetime
    status: AuthorizationStatus
    policy_version: str = Field(min_length=1, max_length=40)
    offer_version: str = Field(min_length=1, max_length=64)
    binding_version: str = Field(default=BINDING_VERSION, min_length=1, max_length=40)
    approval_scheme: ApprovalScheme
    signing_key_id: str | None = Field(default=None, min_length=1, max_length=120)
    approval_signature: str | None = Field(
        default=None,
        min_length=SIGNATURE_HEX_LENGTH,
        max_length=SIGNATURE_HEX_LENGTH,
        pattern=r"^[0-9a-f]+$",
    )
    consumed_at: datetime | None = None

    @model_validator(mode="after")
    def _consumed_at_matches_status(self) -> Authorization:
        """Mirror of the database CHECK constraint: a consumption timestamp
        exists if and only if the artifact is CONSUMED."""
        require(
            (self.status == AuthorizationStatus.CONSUMED) == (self.consumed_at is not None),
            "authorization.consumed_at_matches_status",
            f"status={self.status.value} but consumed_at={self.consumed_at!r}",
        )
        has_key = self.signing_key_id is not None
        has_signature = self.approval_signature is not None
        require(
            has_key == has_signature,
            "authorization.proof_metadata_is_complete",
            "signing_key_id and approval_signature must be present or absent together",
        )
        if self.approval_scheme in {
            ApprovalScheme.POLICY_AUTO,
            ApprovalScheme.LEGACY_SERVER,
        }:
            require(
                not has_key,
                "authorization.unsigned_scheme_has_no_proof",
                f"{self.approval_scheme.value} cannot carry an Ed25519 proof",
            )
        elif self.status == AuthorizationStatus.PENDING:
            require(
                not has_key,
                "authorization.pending_user_approval_has_no_proof",
                "a pending USER_ED25519 authorization cannot already carry a proof",
            )
        elif self.status in {AuthorizationStatus.ACTIVE, AuthorizationStatus.CONSUMED}:
            require(
                has_key,
                "authorization.active_user_approval_has_proof",
                f"{self.status.value} USER_ED25519 authorization is missing its proof",
            )
        return self

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def is_expired_at(self, now: datetime) -> bool:
        return now >= self.expires_at
