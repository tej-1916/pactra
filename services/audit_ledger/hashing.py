"""Canonical serialization + SHA-256 hashing for the audit chain.

The hash covers the semantically meaningful fields of an event plus the prior
event's hash, forming a tamper-evident chain. Canonical JSON (sorted keys,
compact separators, stable datetime encoding) guarantees the same bytes are
hashed regardless of dict ordering. This is tamper-evident, NOT a blockchain.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

GENESIS_HASH = "0" * 64


def _default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=_default,
    )


def compute_event_hash(
    *,
    mission_id: str,
    sequence: int,
    event_type: str,
    actor: str,
    payload: dict[str, Any],
    previous_hash: str,
    created_at: datetime,
) -> str:
    body = canonical_json(
        {
            "mission_id": mission_id,
            "sequence": sequence,
            "event_type": event_type,
            "actor": actor,
            "payload": payload,
            "previous_hash": previous_hash,
            "created_at": created_at.isoformat(),
        }
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()
