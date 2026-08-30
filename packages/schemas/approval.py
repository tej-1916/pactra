"""Canonical LOCAL CRYPTOGRAPHIC APPROVAL PROOF protocol values.

``pactra-user-approval-v1`` signs one server-reconstructed canonical message.
It does not accept arbitrary JSON, caller-provided message bytes, or a
caller-selected algorithm.  The Phase 3 transaction digest remains the sole
commitment to transaction details; this message binds that digest to its
mission, authorization artifact, binding version, and pre-enrolled demo key.
"""

from __future__ import annotations

import uuid
from enum import Enum

from packages.schemas.canonical import canonical_message
from packages.schemas.invariants import require

APPROVAL_DOMAIN = "pactra-user-approval-v1"
APPROVAL_ALGORITHM = "Ed25519"
SIGNATURE_HEX_LENGTH = 128
PUBLIC_KEY_HEX_LENGTH = 64

APPROVAL_MESSAGE_FIELDS: tuple[str, ...] = (
    "authorization_id",
    "mission_id",
    "binding_version",
    "transaction_digest",
    "signing_key_id",
)


class ApprovalScheme(str, Enum):
    """How an authorization became active.

    ``LEGACY_SERVER`` exists only so migration can classify historical
    REQUIRE_APPROVAL/unknown rows without mislabelling them as user-approved.
    New code never issues it and payment verification always rejects it.
    """

    POLICY_AUTO = "POLICY_AUTO"
    USER_ED25519 = "USER_ED25519"
    LEGACY_SERVER = "LEGACY_SERVER"


def approval_message(
    *,
    authorization_id: uuid.UUID,
    mission_id: uuid.UUID,
    binding_version: str,
    transaction_digest: str,
    signing_key_id: str,
) -> bytes:
    """Build the only byte sequence an Ed25519 demo approver may sign."""
    require(
        len(transaction_digest) == 64
        and transaction_digest == transaction_digest.lower()
        and all(c in "0123456789abcdef" for c in transaction_digest),
        "approval.transaction_digest_is_lowercase_sha256_hex",
        "transaction_digest must be exactly 64 lowercase hexadecimal characters",
    )
    require(bool(binding_version), "approval.binding_version_present", "binding_version is empty")
    require(bool(signing_key_id), "approval.signing_key_id_present", "signing_key_id is empty")
    fields = {
        "authorization_id": str(authorization_id),
        "mission_id": str(mission_id),
        "binding_version": binding_version,
        "transaction_digest": transaction_digest,
        "signing_key_id": signing_key_id,
    }
    require(
        tuple(fields) == APPROVAL_MESSAGE_FIELDS,
        "approval.message_fields_complete",
        "approval message field set drifted",
    )
    return canonical_message(APPROVAL_DOMAIN, fields)
