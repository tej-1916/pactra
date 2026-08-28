"""Audit chain verification (Phase 5).

The invariant this module exists to enforce::

    AUDIT EVENT MODIFIED  ->  VERIFICATION FAILURE

WHAT IT NEVER DOES
------------------
It never writes. Not to ``event_hash``, not to ``previous_hash``, not to
``sequence``, not to ``payload``, not to any other table. There is no repair
path, no "recompute on read", no self-healing. A verifier that fixes what it is
supposed to detect converts tamper-evidence into tamper-erasure, and every
corruption test in this phase would then pass for the wrong reason.

It also never re-derives a hash its own way. Recomputation goes through
``compute_event_hash`` — the SAME function the ledger used to write the hash —
so a verifier/writer drift is not a bug this code can develop.

ORDER OF CHECKS, AND WHY
------------------------
1. **Structure.** A row whose ``previous_hash`` is not 64 hex characters, or
   whose payload is not an object, is not an audit event at all. Comparing
   hashes on it would produce a confident but meaningless verdict, so it is
   rejected first.
2. **Position.** Sequences must be exactly ``0..N-1``. This is what catches a
   deleted middle event or an injected one — before any hash is examined,
   because a chain with a hole is broken regardless of what the survivors hash
   to.
3. **Genesis.** Event 0 must carry ``"0" * 64``.
4. **Linkage.** ``event[n].previous_hash == event[n-1].event_hash``.
5. **Content.** The recomputed hash must equal the stored one.

Only the FIRST failure is reported. Tampering with one event invalidates that
event's hash and every link after it; reporting all of them would present one
act of tampering as dozens of findings and bury the position that matters.

WHAT A PER-MISSION CHAIN CANNOT DETECT (stated, not papered over)
-----------------------------------------------------------------
* **Tail truncation.** Deleting the last k events leaves ``0..N-k-1``, which is
  still a contiguous, correctly-linked chain. Detecting it needs an anchor
  outside the chain — a signed head, an external witness, or a cross-mission
  ledger. Phase 5 builds none of those, so this is a documented gap, not a
  covered case.
* **Whole-chain deletion.** A mission with no events is indistinguishable from
  a mission whose events were all removed. Same missing anchor, same gap.

Deleting an event from the MIDDLE is detected (sequence gap), as is reordering,
renumbering, and any edit to a hashed field.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from apps.api.db.models import AuditEventRow
from packages.schemas.audit import AuditReasonCode, AuditVerificationResult
from sqlalchemy.ext.asyncio import AsyncSession

from services.audit_ledger.hashing import (
    GENESIS_HASH,
    HASH_HEX_LENGTH,
    compute_event_hash,
)
from services.audit_ledger.ledger import list_events

_HEX_DIGITS = frozenset("0123456789abcdef")


def _is_hash_shaped(value: object) -> bool:
    """A stored hash must be exactly 64 lowercase hex characters.

    Lowercase specifically: ``hexdigest()`` produces lowercase, so an
    uppercased hash is already a modified hash even if it decodes to the same
    bytes. Accepting it would mean accepting an edited column.
    """
    return (
        isinstance(value, str)
        and len(value) == HASH_HEX_LENGTH
        and all(character in _HEX_DIGITS for character in value)
    )


def _malformed(
    mission_id: uuid.UUID, *, checked: int, sequence: int | None, detail: str
) -> AuditVerificationResult:
    return AuditVerificationResult(
        valid=False,
        mission_id=mission_id,
        events_checked=checked,
        first_invalid_sequence=sequence,
        reason_code=AuditReasonCode.AUDIT_EVENT_MALFORMED,
        detail=detail,
    )


def _structural_failure(
    mission_id: uuid.UUID, *, checked: int, index: int, event: AuditEventRow
) -> AuditVerificationResult | None:
    """Reject a row that is not shaped like an audit event. None if it is fine."""
    sequence = event.sequence if isinstance(event.sequence, int) else None

    if not isinstance(event.sequence, int) or isinstance(event.sequence, bool):
        return _malformed(
            mission_id,
            checked=checked,
            sequence=None,
            detail=f"event at position {index} has a non-integer sequence",
        )
    if event.sequence < 0:
        return _malformed(
            mission_id,
            checked=checked,
            sequence=sequence,
            detail=f"event at position {index} has a negative sequence",
        )
    if not _is_hash_shaped(event.previous_hash):
        return _malformed(
            mission_id,
            checked=checked,
            sequence=sequence,
            detail="previous_hash is not 64 lowercase hex characters",
        )
    if not _is_hash_shaped(event.event_hash):
        return _malformed(
            mission_id,
            checked=checked,
            sequence=sequence,
            detail="event_hash is not 64 lowercase hex characters",
        )
    if not isinstance(event.payload, dict):
        return _malformed(
            mission_id,
            checked=checked,
            sequence=sequence,
            detail="payload is not a JSON object",
        )
    if not isinstance(event.event_type, str) or not event.event_type:
        return _malformed(
            mission_id,
            checked=checked,
            sequence=sequence,
            detail="event_type is empty",
        )
    if not isinstance(event.actor, str) or not event.actor:
        return _malformed(
            mission_id,
            checked=checked,
            sequence=sequence,
            detail="actor is empty",
        )
    if event.created_at is None:
        return _malformed(
            mission_id,
            checked=checked,
            sequence=sequence,
            detail="created_at is absent, so the hashed instant cannot be reproduced",
        )
    return None


def verify_events(
    mission_id: uuid.UUID, events: Sequence[AuditEventRow]
) -> AuditVerificationResult:
    """Verify an ordered event stream. Pure: reads, compares, returns.

    ``events`` is re-sorted by ``sequence`` before anything else. The sequence
    is INSIDE the hash preimage, so the order rows happen to arrive in from the
    database cannot change the verdict — a shuffled retrieval verifies exactly
    as the ordered one does. That is a property worth having explicitly rather
    than inheriting from an ``ORDER BY`` a caller might forget.
    """
    ordered = sorted(events, key=lambda event: (event.sequence, str(event.event_id)))

    if not ordered:
        # An empty chain has nothing to tamper with. It is reported valid with
        # zero events checked — NOT as proof that no events were deleted, which
        # a per-mission chain cannot establish (see the module docstring).
        return AuditVerificationResult(
            valid=True,
            mission_id=mission_id,
            events_checked=0,
            reason_code=AuditReasonCode.AUDIT_VALID,
        )

    for index, event in enumerate(ordered):
        structural = _structural_failure(mission_id, checked=index, index=index, event=event)
        if structural is not None:
            return structural

        if event.sequence != index:
            return AuditVerificationResult(
                valid=False,
                mission_id=mission_id,
                events_checked=index,
                first_invalid_sequence=event.sequence,
                reason_code=AuditReasonCode.AUDIT_SEQUENCE_GAP,
                detail=f"expected sequence {index}, found {event.sequence}",
            )

        if index == 0:
            if event.previous_hash != GENESIS_HASH:
                return AuditVerificationResult(
                    valid=False,
                    mission_id=mission_id,
                    events_checked=0,
                    first_invalid_sequence=event.sequence,
                    reason_code=AuditReasonCode.AUDIT_GENESIS_INVALID,
                    expected_hash=GENESIS_HASH,
                    actual_hash=event.previous_hash,
                    detail="the first event must carry the genesis previous_hash",
                )
        else:
            # Indexed rather than carried in a local: `ordered` is already the
            # authority for order, and a second variable tracking "the previous
            # one" is a place for the two to disagree.
            preceding = ordered[index - 1]
            if event.previous_hash != preceding.event_hash:
                return AuditVerificationResult(
                    valid=False,
                    mission_id=mission_id,
                    events_checked=index,
                    first_invalid_sequence=event.sequence,
                    reason_code=AuditReasonCode.AUDIT_PREVIOUS_HASH_MISMATCH,
                    expected_hash=preceding.event_hash,
                    actual_hash=event.previous_hash,
                    detail="this event does not link to the event before it",
                )

        recomputed = compute_event_hash(
            mission_id=str(event.mission_id),
            sequence=event.sequence,
            event_type=event.event_type,
            actor=event.actor,
            payload=event.payload,
            previous_hash=event.previous_hash,
            created_at=event.created_at,
        )
        if recomputed != event.event_hash:
            return AuditVerificationResult(
                valid=False,
                mission_id=mission_id,
                events_checked=index,
                first_invalid_sequence=event.sequence,
                reason_code=AuditReasonCode.AUDIT_EVENT_HASH_MISMATCH,
                # The recomputed hash is what the CONTENT says; the stored hash
                # is what the row claims. Naming them this way round makes the
                # report read as "the content no longer matches its hash".
                expected_hash=recomputed,
                actual_hash=event.event_hash,
                detail="the event's contents do not hash to its stored event_hash",
            )

    return AuditVerificationResult(
        valid=True,
        mission_id=mission_id,
        events_checked=len(ordered),
        reason_code=AuditReasonCode.AUDIT_VALID,
    )


async def verify_mission_chain(
    session: AsyncSession, mission_id: uuid.UUID
) -> AuditVerificationResult:
    """Load a mission's chain and verify it. READ ONLY.

    ``populate_existing`` is not used and no row is refreshed: the verifier
    reads what ``list_events`` returns and touches nothing. The session is left
    with no pending changes, so a caller that commits after verifying commits
    nothing on the verifier's behalf.
    """
    events = await list_events(session, mission_id)
    return verify_events(mission_id, events)
