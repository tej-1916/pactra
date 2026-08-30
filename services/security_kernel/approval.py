"""Ed25519 verification for the demo user approval trust root.

The request supplies only a key identifier and a signature.  Public-key
resolution is server-owned configuration; there is no enrollment path and no
algorithm selector.  Verification always reconstructs the canonical approval
message from durable authorization values.
"""

from __future__ import annotations

import secrets
import uuid

from apps.api.pactra.config import get_settings
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from packages.schemas.approval import (
    PUBLIC_KEY_HEX_LENGTH,
    SIGNATURE_HEX_LENGTH,
    approval_message,
)
from packages.schemas.domain import ReasonCode


class ApprovalVerificationError(Exception):
    """A proof refusal with a stable externally safe reason code."""

    def __init__(self, reason_code: ReasonCode, detail: str) -> None:
        super().__init__(f"{reason_code.value}: {detail}")
        self.reason_code = reason_code.value
        self.detail = detail


def _decode_lowercase_hex(value: str, *, length: int, label: str) -> bytes:
    if len(value) != length or value != value.lower():
        raise ApprovalVerificationError(
            ReasonCode.AUTHORIZATION_SIGNATURE_MALFORMED,
            f"{label} must be exactly {length} lowercase hexadecimal characters",
        )
    try:
        decoded = bytes.fromhex(value)
    except ValueError as exc:
        raise ApprovalVerificationError(
            ReasonCode.AUTHORIZATION_SIGNATURE_MALFORMED,
            f"{label} is not lowercase hexadecimal",
        ) from exc
    if len(decoded) * 2 != length:
        raise ApprovalVerificationError(
            ReasonCode.AUTHORIZATION_SIGNATURE_MALFORMED,
            f"{label} has the wrong decoded length",
        )
    return decoded


def _trusted_demo_public_key(signing_key_id: str) -> Ed25519PublicKey:
    settings = get_settings()
    configured_id = settings.demo_approver_signing_key_id
    if not secrets.compare_digest(signing_key_id, configured_id):
        raise ApprovalVerificationError(
            ReasonCode.AUTHORIZATION_SIGNING_KEY_UNKNOWN,
            "signing_key_id is not the pre-enrolled demo approver key",
        )

    encoded = settings.demo_approver_public_key_hex
    if encoded is None or not encoded:
        raise ApprovalVerificationError(
            ReasonCode.AUTHORIZATION_SIGNING_KEY_UNKNOWN,
            "the demo approver public key is not configured",
        )
    if (
        len(encoded) != PUBLIC_KEY_HEX_LENGTH
        or encoded != encoded.lower()
        or any(c not in "0123456789abcdef" for c in encoded)
    ):
        raise ApprovalVerificationError(
            ReasonCode.AUTHORIZATION_SIGNING_KEY_UNKNOWN,
            "the configured demo approver public key is malformed",
        )
    try:
        return Ed25519PublicKey.from_public_bytes(bytes.fromhex(encoded))
    except ValueError as exc:
        raise ApprovalVerificationError(
            ReasonCode.AUTHORIZATION_SIGNING_KEY_UNKNOWN,
            "the configured demo approver public key is invalid",
        ) from exc


def verify_user_ed25519_signature(
    *,
    authorization_id: uuid.UUID,
    mission_id: uuid.UUID,
    binding_version: str,
    transaction_digest: str,
    signing_key_id: str,
    signature_hex: str,
) -> None:
    """Verify one proof against the one pre-enrolled demo approver key."""
    signature = _decode_lowercase_hex(
        signature_hex,
        length=SIGNATURE_HEX_LENGTH,
        label="signature",
    )
    public_key = _trusted_demo_public_key(signing_key_id)
    message = approval_message(
        authorization_id=authorization_id,
        mission_id=mission_id,
        binding_version=binding_version,
        transaction_digest=transaction_digest,
        signing_key_id=signing_key_id,
    )
    try:
        public_key.verify(signature, message)
    except InvalidSignature as exc:
        raise ApprovalVerificationError(
            ReasonCode.AUTHORIZATION_SIGNATURE_INVALID,
            "signature does not verify for this authorization challenge",
        ) from exc
