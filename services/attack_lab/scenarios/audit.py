"""AUDIT — a modified event must break verification, and refuse replay.

    AUDIT EVENT MODIFIED -> VERIFICATION FAILURE

Corruption is applied with plain UPDATE / DELETE / INSERT statements that go
around ``append_event`` entirely, because an attacker with database access does
not politely go through the application. That is the same technique the Phase 5
corruption tests use, and it is the only technique that tests the VERIFIER
rather than testing the writer.

WHY THE STATEMENTS ARE BUILT WITH TYPED COLUMNS
----------------------------------------------
An earlier version of this module wrote the tampers as raw SQL strings binding
``str(mission_id)``. SQLAlchemy's ``Uuid`` column stores a dash-less 32-character
hex string on SQLite, so ``WHERE mission_id = '82f8...-...'`` matched nothing.
Every tamper silently became a no-op, the untouched chain verified correctly,
and all six scenarios reported the verifier as broken. A harness that cannot
land its attack will report the system as failing.

Two defences against that recurring: the statements are built from the mapped
columns, so the dialect's own type binding applies and PostgreSQL's native uuid
works identically; and every tamper asserts it actually changed a row. A tamper
that touched nothing raises, which the runner records as ERROR — never as a
blocked attack, and never as a bypass.

WHAT EACH SCENARIO MEASURES
---------------------------
* verification must FAIL with the right reason code for that kind of edit;
* ``replay_mission`` must refuse to project at all — ``trusted`` false and
  ``state`` null, because a projection built from history already known to be
  false is worse than no answer: it looks like one;
* and the tampered row, re-read AFTER verification, must be exactly as the
  attacker left it. Tamper evidence that quietly heals what it detects is not
  tamper evidence.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from apps.api.db.models import AuditEventRow
from packages.schemas.audit import AuditReasonCode
from sqlalchemy import CursorResult, delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from services.attack_lab.models import (
    AttackCategory,
    AttackScenario,
    AttackStatus,
    Observation,
    Severity,
)
from services.attack_lab.scenarios._helpers import constraints, run_mission
from services.attack_lab.scenarios.adversaries import PolicyMutatingMerchant
from services.audit_ledger.replay import replay_mission
from services.audit_ledger.verify import verify_mission_chain

#: The event this module tampers with. Deliberately in the middle of the chain:
#: sequence 0 is the genesis special case and the tail is the documented
#: undetectable region, so neither would exercise the ordinary path.
TARGET_SEQUENCE = 2


class TamperNotApplied(Exception):
    """The corrupting statement changed no rows, so no attack was carried out.

    Raised rather than tolerated. A tamper that silently matched nothing leaves
    an intact chain that verifies correctly, and reporting that as either a
    blocked attack or a bypass would be reporting a measurement that was never
    taken.
    """


TamperFn = Callable[[AsyncSession, uuid.UUID, int], Awaitable[int]]


async def _mission_with_history(context: Any) -> dict[str, Any]:
    """A real mission chain, produced by the kernel rather than hand-written.

    A hand-built chain would only prove the verifier can check a chain the test
    knows how to build. This one carries genuine security violations, a policy
    decision and an authorization, so the events being tampered with are events
    that matter.
    """
    mission_id = await run_mission(
        context,
        merchants=[PolicyMutatingMerchant(price=3499)],
        mission_constraints=constraints(soft_budget_inr=3000, hard_limit_inr=4500),
    )
    async with context.sessionmaker() as session:
        verification = await verify_mission_chain(session, mission_id)
    return {
        "mission_id": mission_id,
        "valid_before": verification.valid,
        "events_before": verification.events_checked,
    }


async def _row_snapshot(
    context: Any, mission_id: uuid.UUID, sequence: int
) -> dict[str, Any] | None:
    async with context.sessionmaker() as session:
        row = (
            await session.execute(
                select(
                    AuditEventRow.event_hash,
                    AuditEventRow.previous_hash,
                    AuditEventRow.payload,
                    AuditEventRow.actor,
                    AuditEventRow.event_type,
                )
                .where(
                    AuditEventRow.mission_id == mission_id,
                    AuditEventRow.sequence == sequence,
                )
                .order_by(AuditEventRow.event_id)
            )
        ).first()
    if row is None:
        return None
    return {
        "event_hash": row[0],
        "previous_hash": row[1],
        "payload": row[2],
        "actor": row[3],
        "event_type": row[4],
    }


async def _event_count(context: Any, mission_id: uuid.UUID) -> int:
    async with context.sessionmaker() as session:
        return int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(AuditEventRow)
                    .where(AuditEventRow.mission_id == mission_id)
                )
            ).scalar_one()
        )


async def _verify_and_replay(context: Any, mission_id: uuid.UUID) -> dict[str, Any]:
    async with context.sessionmaker() as session:
        verification = await verify_mission_chain(session, mission_id)
        replay = await replay_mission(session, mission_id)
    return {
        "valid": verification.valid,
        "reason_code": verification.reason_code.value,
        "first_invalid_sequence": verification.first_invalid_sequence,
        "events_checked": verification.events_checked,
        "replay_trusted": replay.trusted,
        "replay_reason_code": replay.reason_code.value,
        "replay_state_is_null": replay.state is None,
    }


def _where(mission_id: uuid.UUID, sequence: int) -> tuple:
    return (AuditEventRow.mission_id == mission_id, AuditEventRow.sequence == sequence)


async def _run(session: AsyncSession, statement: Any) -> int:
    """Execute a DML statement and return how many rows it actually changed."""
    result: CursorResult = await session.execute(statement)  # type: ignore[assignment]
    return result.rowcount


# --------------------------------------------------------------------------- #
# The tampers. Each returns the number of rows it changed.
# --------------------------------------------------------------------------- #
async def _tamper_payload(session: AsyncSession, mission_id: uuid.UUID, seq: int) -> int:
    return await _run(
        session,
        update(AuditEventRow)
        .where(*_where(mission_id, seq))
        .values(payload={"rewritten": "by the attacker", "attempted_value": 0})
        .execution_options(synchronize_session=False),
    )


async def _tamper_event_hash(session: AsyncSession, mission_id: uuid.UUID, seq: int) -> int:
    return await _run(
        session,
        update(AuditEventRow)
        .where(*_where(mission_id, seq))
        .values(event_hash="a" * 64)
        .execution_options(synchronize_session=False),
    )


async def _tamper_previous_hash(session: AsyncSession, mission_id: uuid.UUID, seq: int) -> int:
    return await _run(
        session,
        update(AuditEventRow)
        .where(*_where(mission_id, seq))
        .values(previous_hash="b" * 64)
        .execution_options(synchronize_session=False),
    )


async def _tamper_actor(session: AsyncSession, mission_id: uuid.UUID, seq: int) -> int:
    return await _run(
        session,
        update(AuditEventRow)
        .where(*_where(mission_id, seq))
        .values(actor="somebody-else")
        .execution_options(synchronize_session=False),
    )


async def _tamper_recomputed(session: AsyncSession, mission_id: uuid.UUID, seq: int) -> int:
    """Edit the payload AND recompute a matching event_hash.

    The strongest single-event forgery available to an attacker who knows the
    hash function: the tampered event is internally consistent. It is caught one
    event LATER, because the next event's ``previous_hash`` still points at the
    original hash — which is the entire reason the chain links at all.
    """
    from services.audit_ledger.hashing import compute_event_hash

    row = (
        await session.execute(select(AuditEventRow).where(*_where(mission_id, seq)).limit(1))
    ).scalar_one_or_none()
    if row is None:
        return 0
    forged_payload = {"rewritten": "by the attacker", "consistent": True}
    forged_hash = compute_event_hash(
        mission_id=str(row.mission_id),
        sequence=row.sequence,
        event_type=row.event_type,
        actor=row.actor,
        payload=forged_payload,
        previous_hash=row.previous_hash,
        created_at=row.created_at,
    )
    return await _run(
        session,
        update(AuditEventRow)
        .where(*_where(mission_id, seq))
        .values(payload=forged_payload, event_hash=forged_hash)
        .execution_options(synchronize_session=False),
    )


async def _tamper_delete_middle(session: AsyncSession, mission_id: uuid.UUID, seq: int) -> int:
    return await _run(
        session,
        delete(AuditEventRow)
        .where(*_where(mission_id, seq))
        .execution_options(synchronize_session=False),
    )


# --------------------------------------------------------------------------- #
# Scenario factory
# --------------------------------------------------------------------------- #
def _tamper_scenario(
    *,
    scenario_id: str,
    name: str,
    severity: Severity,
    expected_reason: AuditReasonCode,
    description: str,
    tamper: TamperFn,
    critical: bool = False,
) -> AttackScenario:
    async def setup(context: Any) -> dict[str, Any]:
        state = await _mission_with_history(context)
        state["row_before_attack"] = await _row_snapshot(
            context, state["mission_id"], TARGET_SEQUENCE
        )
        return state

    async def execute(context: Any, state: dict[str, Any]) -> Observation:
        mission_id = state["mission_id"]

        async with context.sessionmaker() as session:
            changed = await tamper(session, mission_id, TARGET_SEQUENCE)
            await session.commit()

        if changed < 1:
            # The attack did not land. Fail closed: an intact chain verifying
            # correctly says nothing about the verifier's ability to detect an
            # edit that was never made.
            raise TamperNotApplied(
                f"{scenario_id}: the corrupting statement changed {changed} rows; "
                "no tamper was applied and nothing was measured"
            )

        row_after_tamper = await _row_snapshot(context, mission_id, TARGET_SEQUENCE)
        events_after = await _event_count(context, mission_id)
        outcome = await _verify_and_replay(context, mission_id)
        # Re-read AFTER verification: the verifier must have repaired nothing.
        row_after_verify = await _row_snapshot(context, mission_id, TARGET_SEQUENCE)

        detected = not outcome["valid"]
        correct_reason = outcome["reason_code"] == expected_reason.value
        replay_refused = (not outcome["replay_trusted"]) and outcome["replay_state_is_null"]
        verifier_wrote_nothing = row_after_tamper == row_after_verify
        row_actually_changed = state["row_before_attack"] != row_after_tamper
        was_valid_before = bool(state["valid_before"])

        blocked = (
            was_valid_before
            and detected
            and correct_reason
            and replay_refused
            and verifier_wrote_nothing
        )
        return Observation(
            blocked=blocked,
            reason_code=outcome["reason_code"],
            invariant_preserved=detected and replay_refused,
            observed_effects={
                "chain_valid_before_attack": was_valid_before,
                "events_before_attack": state["events_before"],
                "events_after_attack": events_after,
                "rows_changed_by_tamper": changed,
                "target_row_actually_changed": row_actually_changed,
                "tampered_sequence": TARGET_SEQUENCE,
                "tamper_detected": detected,
                "verification_reason_code": outcome["reason_code"],
                "first_invalid_sequence": outcome["first_invalid_sequence"],
                "events_verified_before_break": outcome["events_checked"],
                "replay_trusted": outcome["replay_trusted"],
                "replay_reason_code": outcome["replay_reason_code"],
                "replay_state_withheld": outcome["replay_state_is_null"],
                "verifier_left_the_row_as_the_attacker_left_it": verifier_wrote_nothing,
            },
            evidence=(
                f"{changed} row(s) edited directly in the database at sequence "
                f"{TARGET_SEQUENCE}; verification failed with {outcome['reason_code']} at "
                f"sequence {outcome['first_invalid_sequence']}, replay refused to project, "
                "and the verifier changed nothing"
            ),
        )

    return AttackScenario(
        id=scenario_id,
        name=name,
        category=AttackCategory.AUDIT,
        severity=severity,
        description=description,
        target_invariants=(
            "AUDIT EVENT MODIFIED -> VERIFICATION FAILURE",
            "TAMPERED HISTORY -> REPLAY REFUSED",
        ),
        expected_reason_code=expected_reason.value,
        critical=critical,
        setup=setup,
        execute=execute,
    )


AUDIT_PAYLOAD_TAMPER = _tamper_scenario(
    scenario_id="audit_payload_tamper",
    name="Audit payload tampering",
    severity=Severity.CRITICAL,
    expected_reason=AuditReasonCode.AUDIT_EVENT_HASH_MISMATCH,
    description=(
        "A historical event's payload is rewritten directly in the database — the "
        "shape an attacker rewriting history would take. The event no longer "
        "hashes to its stored event_hash."
    ),
    tamper=_tamper_payload,
    critical=True,
)

AUDIT_HASH_TAMPER = _tamper_scenario(
    scenario_id="audit_hash_tamper",
    name="Audit event_hash tampering",
    severity=Severity.CRITICAL,
    expected_reason=AuditReasonCode.AUDIT_EVENT_HASH_MISMATCH,
    description=(
        "The stored event_hash is replaced with a different well-formed hash, so "
        "the content no longer matches the hash recorded beside it."
    ),
    tamper=_tamper_event_hash,
    critical=True,
)

AUDIT_CHAIN_TAMPER = _tamper_scenario(
    scenario_id="audit_chain_tamper",
    name="Audit chain linkage tampering",
    severity=Severity.CRITICAL,
    expected_reason=AuditReasonCode.AUDIT_PREVIOUS_HASH_MISMATCH,
    description=(
        "An event's previous_hash is rewritten so it no longer links to the event "
        "before it — an attacker attempting to splice the chain."
    ),
    tamper=_tamper_previous_hash,
    critical=True,
)

AUDIT_ACTOR_TAMPER = _tamper_scenario(
    scenario_id="audit_actor_tamper",
    name="Audit actor tampering",
    severity=Severity.HIGH,
    expected_reason=AuditReasonCode.AUDIT_EVENT_HASH_MISMATCH,
    description=(
        "The recorded actor is rewritten, reattributing an action to a different "
        "principal. The actor is inside the hash preimage, so the edit breaks it."
    ),
    tamper=_tamper_actor,
)

AUDIT_RECOMPUTED_HASH_TAMPER = _tamper_scenario(
    scenario_id="audit_recomputed_hash_tamper",
    name="Audit payload edit WITH a recomputed hash",
    severity=Severity.CRITICAL,
    expected_reason=AuditReasonCode.AUDIT_PREVIOUS_HASH_MISMATCH,
    description=(
        "The strongest single-event forgery: the payload is rewritten AND a "
        "matching event_hash is recomputed, so the tampered event is internally "
        "consistent. It is caught one event later, because the NEXT event's "
        "previous_hash still points at the original hash."
    ),
    tamper=_tamper_recomputed,
    critical=True,
)

AUDIT_MIDDLE_EVENT_DELETED = _tamper_scenario(
    scenario_id="audit_middle_event_deleted",
    name="Audit middle-event deletion",
    severity=Severity.CRITICAL,
    expected_reason=AuditReasonCode.AUDIT_SEQUENCE_GAP,
    description=(
        "An event is deleted from the MIDDLE of the chain — an attacker removing "
        "the record of a refused escalation. The surviving sequences are no longer "
        "the contiguous run 0..N-1."
    ),
    tamper=_tamper_delete_middle,
    critical=True,
)

# --------------------------------------------------------------------------- #
# Event injection — two layers, measured separately
# --------------------------------------------------------------------------- #


async def _injection_setup(context: Any) -> dict[str, Any]:
    return await _mission_with_history(context)


async def _injection_execute(context: Any, state: dict[str, Any]) -> Observation:
    """Insert a fabricated approval two ways, because two controls answer.

    (a) **Duplicate sequence.** Refused by ``UNIQUE(mission_id, sequence)`` — the
        STORAGE layer, below the verifier. The forged row never lands, so there
        is nothing for verification to detect. This is the stronger outcome and
        it is recorded as what it is: a refusal at the database, not a detection.

    (b) **Fresh sequence past the end.** The unique index has no objection, so
        the row lands and the VERIFIER has to catch it. It does, as a sequence
        gap: the chain is no longer the contiguous run 0..N-1.

    Reporting only (a) would credit the verifier with a defence the database
    provided; reporting only (b) would miss that the database refuses the
    obvious attempt outright. Both are measured.
    """
    from sqlalchemy.exc import IntegrityError

    mission_id = state["mission_id"]
    before = state["events_before"]

    forged = {
        "event_type": "APPROVAL_REQUESTED",
        "actor": "attacker",
        "payload": {"forged": True, "authorization_id": str(uuid.uuid4())},
    }

    # (a) duplicate sequence
    duplicate_refused = False
    duplicate_error: str | None = None
    async with context.sessionmaker() as session:
        anchor = (
            await session.execute(
                select(AuditEventRow).where(*_where(mission_id, TARGET_SEQUENCE)).limit(1)
            )
        ).scalar_one_or_none()
        try:
            await session.execute(
                insert(AuditEventRow).values(
                    event_id=uuid.uuid4(),
                    mission_id=mission_id,
                    sequence=TARGET_SEQUENCE,
                    previous_hash=anchor.previous_hash if anchor else "0" * 64,
                    event_hash="c" * 64,
                    created_at=anchor.created_at if anchor else None,
                    **forged,
                )
            )
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            duplicate_refused = True
            duplicate_error = type(exc).__name__

    after_duplicate = await _event_count(context, mission_id)
    verdict_after_duplicate = await _verify_and_replay(context, mission_id)

    # (b) fresh sequence past the end, leaving a gap the index cannot see
    gap_sequence = before + 5
    async with context.sessionmaker() as session:
        anchor = (
            await session.execute(
                select(AuditEventRow)
                .where(AuditEventRow.mission_id == mission_id)
                .order_by(AuditEventRow.sequence.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        injected = await _run(
            session,
            insert(AuditEventRow).values(
                event_id=uuid.uuid4(),
                mission_id=mission_id,
                sequence=gap_sequence,
                previous_hash=anchor.event_hash if anchor else "0" * 64,
                event_hash="d" * 64,
                created_at=anchor.created_at if anchor else None,
                **forged,
            ),
        )
        await session.commit()

    if injected < 1:
        raise TamperNotApplied("audit_event_injection: the appended forged row was not inserted")

    verdict_after_gap = await _verify_and_replay(context, mission_id)

    # (a) must have been refused by storage AND left the chain intact.
    storage_refused = duplicate_refused and after_duplicate == before
    chain_intact_after_duplicate = bool(verdict_after_duplicate["valid"])
    # (b) must have been caught by the verifier, and replay must refuse.
    verifier_detected = not verdict_after_gap["valid"]
    correct_reason = verdict_after_gap["reason_code"] == AuditReasonCode.AUDIT_SEQUENCE_GAP.value
    replay_refused = (
        not verdict_after_gap["replay_trusted"] and verdict_after_gap["replay_state_is_null"]
    )

    blocked = (
        storage_refused
        and chain_intact_after_duplicate
        and verifier_detected
        and correct_reason
        and replay_refused
    )
    return Observation(
        blocked=blocked,
        reason_code=verdict_after_gap["reason_code"],
        invariant_preserved=verifier_detected and replay_refused,
        observed_effects={
            "events_before_attack": before,
            "duplicate_sequence_insert_refused_by_storage": duplicate_refused,
            "duplicate_sequence_error": duplicate_error,
            "events_after_duplicate_attempt": after_duplicate,
            "chain_valid_after_duplicate_attempt": chain_intact_after_duplicate,
            "appended_forged_row_at_sequence": gap_sequence,
            "verifier_detected_injection": verifier_detected,
            "verification_reason_code": verdict_after_gap["reason_code"],
            "first_invalid_sequence": verdict_after_gap["first_invalid_sequence"],
            "replay_trusted": verdict_after_gap["replay_trusted"],
            "replay_state_withheld": verdict_after_gap["replay_state_is_null"],
        },
        evidence=(
            "a forged APPROVAL_REQUESTED at a duplicate sequence was refused by "
            "UNIQUE(mission_id, sequence) before it could land; the same row appended "
            f"at sequence {gap_sequence} landed and was caught by the verifier as "
            f"{verdict_after_gap['reason_code']}, and replay refused to project"
        ),
    )


AUDIT_EVENT_INJECTION = AttackScenario(
    id="audit_event_injection",
    name="Audit event injection",
    category=AttackCategory.AUDIT,
    severity=Severity.CRITICAL,
    description=(
        "A fabricated APPROVAL_REQUESTED event attributed to `attacker` is inserted "
        "twice: once at a duplicated sequence (refused by the UNIQUE index before it "
        "lands) and once appended past the end (landed, then caught by the verifier "
        "as a sequence gap). Both layers are measured separately."
    ),
    target_invariants=(
        "AUDIT EVENT MODIFIED -> VERIFICATION FAILURE",
        "TAMPERED HISTORY -> REPLAY REFUSED",
        "UNIQUE(mission_id, sequence) -> APPEND-ONLY ORDERING",
    ),
    expected_reason_code=AuditReasonCode.AUDIT_SEQUENCE_GAP.value,
    critical=True,
    setup=_injection_setup,
    execute=_injection_execute,
)


# --------------------------------------------------------------------------- #
# KNOWN LIMITATION — tail truncation
# --------------------------------------------------------------------------- #

#: How many trailing events the truncation scenario removes. Fewer than the
#: chain length, so what remains is a genuine truncated chain rather than an
#: empty one — the empty case is a different (and also undetectable) gap.
TRUNCATED_TAIL_EVENTS = 3


async def _truncation_setup(context: Any) -> dict[str, Any]:
    return await _mission_with_history(context)


async def _truncation_execute(context: Any, state: dict[str, Any]) -> Observation:
    """Delete the LAST k events and observe that verification still passes.

    This is NOT a blocked attack and is never counted as one. Deleting the tail
    leaves sequences 0..N-k-1 — still contiguous, still correctly linked, still
    hashing correctly. Detecting it requires an anchor OUTSIDE the chain: a
    signed head, an external witness, or a cross-mission ledger. Phase 5 built
    none of those and Phase 6 does not pretend otherwise.

    The scenario exists so the boundary is MEASURED and reported on every run,
    rather than left as a sentence in a document that could quietly stop being
    true — or quietly start being false.
    """
    mission_id = state["mission_id"]
    before = state["events_before"]
    cutoff = before - TRUNCATED_TAIL_EVENTS

    async with context.sessionmaker() as session:
        deleted = await _run(
            session,
            delete(AuditEventRow)
            .where(
                AuditEventRow.mission_id == mission_id,
                AuditEventRow.sequence >= cutoff,
            )
            .execution_options(synchronize_session=False),
        )
        await session.commit()

    if deleted < 1:
        raise TamperNotApplied(
            "audit_tail_truncation: no events were deleted; nothing was measured"
        )

    remaining = await _event_count(context, mission_id)
    outcome = await _verify_and_replay(context, mission_id)
    undetected = bool(outcome["valid"])

    # `blocked=False` is the honest record of a gap. The KNOWN_LIMITATION
    # category keeps this out of the attack block rate in BOTH directions: it is
    # neither a defence that worked nor a vulnerability that was found.
    return Observation(
        blocked=not undetected,
        reason_code=outcome["reason_code"],
        invariant_preserved=None,
        observed_effects={
            "events_before_truncation": before,
            "events_deleted": deleted,
            "events_after_truncation": remaining,
            "chain_still_verifies": undetected,
            "verification_reason_code": outcome["reason_code"],
            "events_checked_after_truncation": outcome["events_checked"],
            "replay_trusted": outcome["replay_trusted"],
            "detection_requires": (
                "an anchor outside the chain: a signed head, an external witness, "
                "or a cross-mission ledger"
            ),
            "counted_as_a_blocked_attack": False,
        },
        evidence=(
            f"{deleted} trailing events deleted, {remaining} remain; the surviving chain "
            "is still contiguous and correctly linked, so per-mission verification "
            "cannot detect it. Documented limitation, NOT a blocked attack."
        ),
    )


AUDIT_TAIL_TRUNCATION = AttackScenario(
    id="audit_tail_truncation",
    name="Audit tail truncation (KNOWN LIMITATION)",
    category=AttackCategory.KNOWN_LIMITATION,
    severity=Severity.HIGH,
    description=(
        "The last three events of a valid chain are deleted. Per-mission hash "
        "chaining CANNOT detect this — the survivors remain contiguous and "
        "correctly linked. Recorded as a measured limitation and deliberately "
        "excluded from the attack block rate rather than counted as blocked."
    ),
    target_invariants=(
        "KNOWN LIMITATION: TAIL TRUNCATION -> UNDETECTABLE WITHOUT AN EXTERNAL ANCHOR",
    ),
    expected_status=AttackStatus.NOT_BLOCKED,
    expected_reason_code=AuditReasonCode.AUDIT_VALID.value,
    setup=_truncation_setup,
    execute=_truncation_execute,
)


SCENARIOS = (
    AUDIT_PAYLOAD_TAMPER,
    AUDIT_HASH_TAMPER,
    AUDIT_CHAIN_TAMPER,
    AUDIT_ACTOR_TAMPER,
    AUDIT_RECOMPUTED_HASH_TAMPER,
    AUDIT_MIDDLE_EVENT_DELETED,
    AUDIT_EVENT_INJECTION,
    AUDIT_TAIL_TRUNCATION,
)
