#!/usr/bin/env python3
"""External signer for PACTRA's LOCAL CRYPTOGRAPHIC APPROVAL PROOF demo.

The DEMO USER-CONTROLLED SIGNING KEY stays in a caller-selected path outside
the PACTRA repository.  PACTRA receives only a key identifier and signature.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from packages.schemas.approval import ApprovalScheme, approval_message

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _outside_repository(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(REPOSITORY_ROOT)
    except ValueError:
        return resolved
    raise ValueError("private key path must be outside the PACTRA repository")


def _write_private_key(path: Path, key: Ed25519PrivateKey) -> None:
    path = _outside_repository(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite existing key: {path}")
    encoded = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, encoded)
    finally:
        os.close(descriptor)
    os.chmod(path, 0o600)


def _load_private_key(path: Path) -> Ed25519PrivateKey:
    path = _outside_repository(path)
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise PermissionError(f"private key permissions must be 0600; found {mode:04o}")
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise TypeError("private key is not Ed25519")
    return key


def _safe_api_base(value: str) -> str:
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("API base must be an absolute http(s) URL")
    if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("plaintext HTTP is allowed only for a loopback demo server")
    return value.rstrip("/")


def _request_json(url: str, *, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"content-type": "application/json"} if data is not None else {},
        method="POST" if data is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"PACTRA returned HTTP {exc.code}: {detail}") from exc


def _validated_challenge(challenge: dict) -> bytes:
    if challenge.get("approval_scheme") != ApprovalScheme.USER_ED25519.value:
        raise ValueError("challenge is not USER_ED25519")
    reconstructed = approval_message(
        authorization_id=uuid.UUID(challenge["authorization_id"]),
        mission_id=uuid.UUID(challenge["mission_id"]),
        binding_version=challenge["binding_version"],
        transaction_digest=challenge["transaction_digest"],
        signing_key_id=challenge["signing_key_id"],
    )
    try:
        supplied = bytes.fromhex(challenge["approval_message_hex"])
    except (KeyError, ValueError) as exc:
        raise ValueError("challenge approval_message_hex is malformed") from exc
    if reconstructed != supplied:
        raise ValueError("challenge message bytes disagree with its canonical fields")
    return reconstructed


def _display_challenge(challenge: dict) -> None:
    transaction = challenge["transaction"]
    print("PACTRA LOCAL CRYPTOGRAPHIC APPROVAL PROOF")
    print(f"authorization: {challenge['authorization_id']}")
    print(f"mission:       {challenge['mission_id']}")
    print(f"merchant:      {transaction['merchant']}")
    print(f"product:       {transaction['product']}")
    print(f"quantity:      {transaction['quantity']}")
    print(f"amount:        {transaction['amount']} {transaction['currency']}")
    print(f"expiry:        {transaction['expiry']}")
    print(f"digest:        {challenge['transaction_digest']}")
    print()
    print("The nonce remains server-held; this signer validates the server-generated")
    print("canonical challenge but cannot independently reconstruct transaction_digest.")


def generate(args: argparse.Namespace) -> int:
    key = Ed25519PrivateKey.generate()
    path = _outside_repository(args.private_key_path)
    _write_private_key(path, key)
    public_hex = (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        .hex()
    )
    print(
        json.dumps(
            {
                "private_key_path": str(path),
                "private_key_permissions": "0600",
                "signing_key_id": args.signing_key_id,
                "demo_approver_public_key_hex": public_hex,
            },
            indent=2,
        )
    )
    return 0


def sign(args: argparse.Namespace) -> int:
    api_base = _safe_api_base(args.api_base)
    key = _load_private_key(args.private_key_path)
    challenge_url = f"{api_base}/api/v1/missions/{args.mission_id}/authorization/challenge"
    challenge = _request_json(challenge_url)
    if challenge["signing_key_id"] != args.signing_key_id:
        raise ValueError("challenge signing_key_id does not match the selected local key")
    message = _validated_challenge(challenge)
    _display_challenge(challenge)
    if not args.yes:
        answer = input("Sign this exact transaction? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            print("Not signed.")
            return 1

    payload = {
        "signing_key_id": args.signing_key_id,
        "signature": key.sign(message).hex(),
    }
    if args.submit:
        approval_url = f"{api_base}/api/v1/missions/{args.mission_id}/authorization/approve"
        result = _request_json(approval_url, payload=payload)
        print(json.dumps({"submitted": True, "authorization": result}, indent=2))
    else:
        print(json.dumps(payload, indent=2))
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)

    generate_parser = commands.add_parser("generate", help="generate an external demo key")
    generate_parser.add_argument("--private-key-path", required=True, type=Path)
    generate_parser.add_argument("--signing-key-id", required=True)
    generate_parser.set_defaults(handler=generate)

    sign_parser = commands.add_parser("sign", help="fetch, display, and sign one challenge")
    sign_parser.add_argument("--private-key-path", required=True, type=Path)
    sign_parser.add_argument("--signing-key-id", required=True)
    sign_parser.add_argument("--mission-id", required=True, type=uuid.UUID)
    sign_parser.add_argument("--api-base", default="http://127.0.0.1:8000")
    sign_parser.add_argument("--submit", action="store_true")
    sign_parser.add_argument("--yes", action="store_true", help="skip interactive confirmation")
    sign_parser.set_defaults(handler=sign)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except (OSError, TypeError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover - exercised as a command
    raise SystemExit(main())
