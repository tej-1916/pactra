"""Canonical serialization + domain-separated SHA-256 digests.

This module exists so security digests are **never** built by concatenating
strings. Naive concatenation is ambiguous: ``merchant_id="ab" | product_id="c"``
and ``merchant_id="a" | product_id="bc"`` produce identical bytes, so two
different transactions would share a digest and one could be substituted for
the other after approval.

Three properties remove that ambiguity:

1. **Structured encoding.** Fields are encoded as a JSON object with sorted
   keys and compact separators. Field *names* are part of the preimage and JSON
   delimits every value, so a value can never bleed across a field boundary.
2. **Type tagging.** Every value is encoded as ``[tag, encoded_value]`` — for
   example ``["i", 3799]`` versus ``["s", "3799"]``. Cross-type confusion
   (integer 1 vs. string "1" vs. boolean true) cannot collide.
3. **Domain separation.** The digest preimage is prefixed with a domain string
   and a separator byte, so a digest computed for one purpose can never be
   replayed as a digest for another.

Deliberate restrictions:

* ``float`` is **rejected**. Binary floats have no canonical decimal form, so
  hashing them is not reproducible across platforms or serialization round
  trips. Callers scale to integers (e.g. a rating of 4.6 becomes 460).
* ``datetime`` must be timezone-aware. A naive datetime has no single instant,
  which would make the digest depend on the reader's locale.
* Unknown types raise ``InvariantViolation`` rather than being stringified.
  Silent ``str(value)`` coercion is how a digest quietly stops covering what it
  claims to cover.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timezone

from packages.schemas.invariants import require

# Values a canonical digest may cover. Deliberately narrow — see module docstring.
CanonicalValue = str | int | bool | datetime | None

# ASCII unit separator between the domain string and the encoded body.
_DOMAIN_SEPARATOR = b"\x1f"

# Fixed-width UTC timestamp format: always microseconds, always "Z".
_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


def encode_timestamp(value: datetime) -> str:
    """Encode a timezone-aware datetime as fixed-precision UTC."""
    require(
        value.tzinfo is not None and value.utcoffset() is not None,
        "canonical.timestamp_is_timezone_aware",
        "naive datetimes have no single instant and cannot be canonically hashed",
    )
    return value.astimezone(timezone.utc).strftime(_TIMESTAMP_FORMAT)


def _encode_value(field: str, value: CanonicalValue) -> list:
    """Encode one value as ``[type_tag, payload]``."""
    # bool must be tested before int: bool is a subclass of int in Python, and
    # collapsing True to 1 would make two different transactions hash alike.
    if isinstance(value, bool):
        return ["b", value]
    if isinstance(value, int):
        return ["i", value]
    if isinstance(value, str):
        return ["s", value]
    if isinstance(value, datetime):
        return ["t", encode_timestamp(value)]
    if value is None:
        return ["n", None]
    require(
        False,
        "canonical.value_type_is_supported",
        f"field '{field}' has unsupported type {type(value).__name__} "
        f"(floats are rejected: they have no canonical form — scale to an integer)",
    )
    raise AssertionError("unreachable")  # pragma: no cover


def canonical_bytes(fields: Mapping[str, CanonicalValue]) -> bytes:
    """Deterministic ASCII encoding of a field mapping.

    Sorted keys make the output independent of dict insertion order;
    ``ensure_ascii=True`` makes it independent of the reader's Unicode
    handling, so the same fields always hash to the same bytes.
    """
    encoded = {name: _encode_value(name, value) for name, value in fields.items()}
    return json.dumps(
        encoded,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def canonical_message(domain: str, fields: Mapping[str, CanonicalValue]) -> bytes:
    """Domain-separated canonical bytes suitable for hashing or signing.

    This is the one repository-wide envelope for security messages.  Callers
    provide canonical values, never request JSON or caller-provided bytes.
    """
    require(bool(domain), "canonical.message_has_domain", "a message must be domain-separated")
    return domain.encode("ascii") + _DOMAIN_SEPARATOR + canonical_bytes(fields)


def canonical_digest(domain: str, fields: Mapping[str, CanonicalValue]) -> str:
    """SHA-256 over ``domain || 0x1f || canonical_bytes(fields)``, as lowercase hex."""
    return hashlib.sha256(canonical_message(domain, fields)).hexdigest()
