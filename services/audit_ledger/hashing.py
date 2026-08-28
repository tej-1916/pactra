"""Canonical serialization + SHA-256 hashing for the audit chain.

The hash covers the semantically meaningful fields of an event plus the prior
event's hash, forming a tamper-evident chain. Canonical JSON (sorted keys,
compact separators, stable datetime encoding) guarantees the same bytes are
hashed regardless of dict ordering. This is tamper-evident, NOT a blockchain.

ONE FUNCTION, BOTH DIRECTIONS
-----------------------------
``compute_event_hash`` is the only place an event hash is ever produced. The
ledger calls it when appending; the Phase 5 verifier calls it when recomputing.
There is deliberately no second "verification" hash function: a verifier that
computes hashes slightly differently from the writer either reports tampering
that did not happen or misses tampering that did, and the drift between the two
implementations stays invisible until it matters.

WHY ``created_at`` IS NORMALIZED HERE
-------------------------------------
``created_at`` is inside the preimage, so the verifier must present the exact
same instant the writer did. The writer always passes an aware UTC value, but
SQLite has no timezone-aware type and hands back a NAIVE datetime on read, whose
``isoformat()`` omits the ``+00:00`` offset — so recomputing from a persisted
row produced a different hash than the one stored beside it.

Normalizing with ``as_utc`` INSIDE this function fixes that for both callers at
once. It is exact rather than a guess: values are written as UTC
unconditionally, so attaching UTC on read restores the original instant. For an
input that is already aware UTC — which is every value the writer passes — the
encoding is byte-identical, so no historical event hash changes.

COMPATIBILITY NOTE (deliberate, not an oversight)
-------------------------------------------------
This canonicalization is NOT the type-tagged, domain-separated encoder in
``packages/schemas/canonical.py`` used for transaction digests. That encoder is
stronger, but switching the audit chain to it would change the preimage of every
event and invalidate every ``event_hash`` already written. Historical hash
semantics are preserved instead, and the difference is documented rather than
silently reconciled. See docs/architecture.md, "Audit payload canonicalization".
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from packages.schemas.domain import as_utc

GENESIS_HASH = "0" * 64

#: Length of a hex-encoded SHA-256 digest. The verifier uses it to reject a
#: structurally impossible hash before bothering to recompute anything.
HASH_HEX_LENGTH = 64


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


def canonical_event_body(
    *,
    mission_id: str,
    sequence: int,
    event_type: str,
    actor: str,
    payload: dict[str, Any],
    previous_hash: str,
    created_at: datetime,
) -> str:
    """The exact string that gets hashed.

    Exposed so a test can inspect the preimage without reimplementing it — the
    one thing a hash test must never do.
    """
    return canonical_json(
        {
            "mission_id": mission_id,
            "sequence": sequence,
            "event_type": event_type,
            "actor": actor,
            "payload": payload,
            "previous_hash": previous_hash,
            # Normalized so a value read back from a timezone-naive store hashes
            # identically to the aware value that was written.
            "created_at": as_utc(created_at).isoformat(),
        }
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
    body = canonical_event_body(
        mission_id=mission_id,
        sequence=sequence,
        event_type=event_type,
        actor=actor,
        payload=payload,
        previous_hash=previous_hash,
        created_at=created_at,
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()
