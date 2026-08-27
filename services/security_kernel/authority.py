"""Authority lattice enforcement.

A lower-authority source may never modify state owned by a higher-authority
source. Violations raise AuthorityEscalation (reason code AUTHORITY_ESCALATION).
"""

from __future__ import annotations

from typing import Any

from packages.schemas.provenance import AuthorityLevel, Provenanced

REASON_CODE = "AUTHORITY_ESCALATION"


class AuthorityEscalation(Exception):
    """Raised when lower-authority data attempts to write higher-authority state."""

    reason_code = REASON_CODE

    def __init__(self, *, source: AuthorityLevel, target: AuthorityLevel, field: str) -> None:
        super().__init__(
            f"{REASON_CODE}: source={source.name} attempted to write "
            f"'{field}' owned by {target.name}"
        )
        self.source = source
        self.target = target
        self.field = field


def can_write(source: AuthorityLevel, target: AuthorityLevel) -> bool:
    """True iff `source` is authorized to write state owned by `target`."""
    return source >= target


def guard_write(source: AuthorityLevel, target: AuthorityLevel, *, field: str) -> None:
    if not can_write(source, target):
        raise AuthorityEscalation(source=source, target=target, field=field)


def assert_can_write(
    field: str, incoming: Provenanced[Any], required_authority: AuthorityLevel
) -> None:
    """Guard writing `incoming` into a field that requires `required_authority`."""
    guard_write(incoming.authority, required_authority, field=field)


def merge_keep_higher(
    field: str, current: Provenanced[Any], incoming: Provenanced[Any]
) -> Provenanced[Any]:
    """Return the value that should win. An incoming value may only override the
    current one if its authority is >= the current authority; otherwise this is
    an escalation attempt and the current (higher-authority) value is protected.
    """
    if incoming.authority < current.authority:
        raise AuthorityEscalation(source=incoming.authority, target=current.authority, field=field)
    return incoming
