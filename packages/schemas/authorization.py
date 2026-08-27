"""Authorization artifact — the explicit domain object Phase 3 introduces.

HONEST SCOPING: this is a **server-issued authorization artifact**, not a
cryptographically signed one. Nothing in Phase 3 signs anything and nothing
verifies a signature. The artifact is authoritative because it is minted, held,
and consumed entirely inside the trusted server boundary — never because it
carries a verifiable user signature. The 256-bit ``nonce`` is server-held
entropy that makes each authorization unique and its digest unpredictable; it
is not a key, not a token issued to a client, and is never disclosed.

If and when real user signing is implemented, this artifact gains a signature
field and a verification step, and the docs change to match. Until then the
name does not claim a guarantee the code cannot deliver.

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
        return self

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def is_expired_at(self, now: datetime) -> bool:
        return now >= self.expires_at
