"""Explicit invariant errors (typed primitive, like provenance.py).

Lives in ``packages`` because both the schema layer (``kernel.py``) and the
security kernel enforce invariants with it; ``packages`` must never import from
``services``.

Security invariants must NEVER be expressed with `assert`: assertions are
stripped when Python runs with `-O`, which would silently delete the check in
exactly the deployment mode where it matters most. `require()` raises an
ordinary exception that survives optimization and carries a reason code into
the audit trail.
"""

from __future__ import annotations

REASON_CODE = "INVARIANT_VIOLATION"


class InvariantViolation(Exception):
    """A kernel invariant that must hold unconditionally did not hold."""

    reason_code = REASON_CODE

    def __init__(self, invariant: str, detail: str) -> None:
        super().__init__(f"{REASON_CODE}: {invariant} — {detail}")
        self.invariant = invariant
        self.detail = detail


def require(condition: bool, invariant: str, detail: str) -> None:
    """Raise InvariantViolation unless `condition` holds."""
    if not condition:
        raise InvariantViolation(invariant, detail)
