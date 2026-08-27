"""Protected policy register.

Holds user-policy values at their authoritative level and adjudicates every
attempt to change them through the authority lattice. A lower-authority write
(e.g. a merchant claim) raises AuthorityEscalation and the protected value is
left untouched.

The register covers the full set of security-sensitive policy fields, not just
budgets: currency, minimum rating, merchant allow/block lists and minimum
merchant trust are all ground the mission is judged on, so all of them are held
at USER_POLICY authority (see `ingress.PROTECTED_POLICY_FIELDS`).
"""

from __future__ import annotations

from typing import Any

from packages.schemas.invariants import require
from packages.schemas.provenance import Provenanced

from services.security_kernel.authority import merge_keep_higher


class ProtectedPolicyRegister:
    def __init__(self, values: dict[str, Provenanced[Any]]) -> None:
        self._values = dict(values)

    def fields(self) -> tuple[str, ...]:
        return tuple(self._values)

    def get(self, field: str) -> Provenanced[Any]:
        require(
            field in self._values,
            "policy_register.field_is_protected",
            f"'{field}' is not a protected policy field",
        )
        return self._values[field]

    def is_protected(self, field: str) -> bool:
        return field in self._values

    def apply(self, field: str, incoming: Provenanced[Any]) -> Provenanced[Any]:
        """Attempt to write `incoming` into `field`. Raises AuthorityEscalation
        if the incoming authority is lower than the protected value's; on success
        the (equal-or-higher) value wins and is stored."""
        current = self.get(field)
        updated = merge_keep_higher(field, current, incoming)
        self._values[field] = updated
        return updated
