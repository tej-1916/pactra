"""Payload key canonicalization and the security-reserved field set.

TWO ATTACKS LIVE IN KEY NAMES, AND THEY ARE DIFFERENT ATTACKS
-------------------------------------------------------------
**Smuggling.** A payload declares ``policy_override``, ``merchant_trust``,
``authorization_valid`` or ``capabilities`` and hopes some layer reads it. The
answer is refusal, not silence. Dropping the key works for exactly as long as
nobody adds a model field with a matching name; on the day somebody does,
"silently dropped" becomes "silently honoured" and no diff shows the change.
Refusing means an external source that tries it gets an error with a reason
code, and the attempt is visible.

**Aliasing.** A payload declares BOTH ``merchant_id`` and ``merchantId``, or
``Policy-Override`` beside ``policy_override``. Whichever the parser reads last
decides the meaning, and the sender picks the order. There is no correct
resolution — the sender has stated two things — so the payload is refused.

Both defences run off ONE normalization (case-folded, separators removed), which
is what makes ``POLICY_OVERRIDE``, ``policy-override`` and ``PolicyOverride``
the same key for the purpose of the reserved-field check. A reserved-field list
matched against raw spellings would be a list of the spellings its author
happened to think of.

SCOPE: TOP LEVEL ONLY, DELIBERATELY
-----------------------------------
The scan applies to the top level of a protocol message and to a tool call's
arguments — the places a field would have to be to be read as security state.
It deliberately does NOT recurse into ``RawMerchantOffer.claims``, which exists
precisely to carry merchant claims about protected policy fields so the
AUTHORITY LATTICE can adjudicate them and record a ``SECURITY_VIOLATION``.
Refusing them here would delete a control that already works, and would replace
"the attempt was caught and audited" with "the attempt was never seen".
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from services.adapters.errors import AmbiguousProtocolField, ReservedFieldRejected

#: Field names an external source may never set, matched after normalization.
#:
#: Four groups, each for its own reason:
#:   * kernel security state    - authority, capability, trust, taint, principal
#:   * authorization material   - nonce, digest, artifact identity and status
#:   * protected user policy    - the ``PROTECTED_POLICY_FIELDS`` register
#:   * adapter identity         - adapter_id and friends are SERVER-owned
RESERVED_SECURITY_FIELDS: frozenset[str] = frozenset(
    {
        # kernel security state
        "authority",
        "authoritylevel",
        "capability",
        "capabilities",
        "capabilityset",
        "paymentexecute",
        "refundexecute",
        "policymodify",
        "authorizationissue",
        "merchantmodify",
        "trust",
        "trusted",
        "trustlevel",
        "tainted",
        "taint",
        "principal",
        "system",
        "systempolicy",
        "provenance",
        # authorization material and artifacts
        "authorization",
        "authorizationid",
        "authorizationvalid",
        "authorizationstatus",
        "nonce",
        "transactiondigest",
        "digest",
        "signature",
        "signed",
        "verified",
        "consumedat",
        "bindingversion",
        # protected user policy (services/security_kernel/ingress.py)
        "policyoverride",
        "policyversion",
        "softbudgetinr",
        "hardlimitinr",
        "minrating",
        "allowedmerchants",
        "blockedmerchants",
        "minmerchanttrust",
        # server-owned merchant reputation and adapter identity
        "merchanttrust",
        "merchanttrustscore",
        "trustscore",
        "merchantname",
        "adapterid",
        "adapterfamily",
        "adapterversion",
        # advisory risk is computed, never supplied (Phase 7 stays advisory)
        "riskscore",
        "riskband",
        "riskrecommendation",
    }
)


def normalize_key(key: str) -> str:
    """Case-fold and strip separators, so spelling variants collapse to one key.

    ``merchantId``, ``merchant_id``, ``MERCHANT-ID`` and ``Merchant Id`` all
    normalize to ``merchantid``. This is used for BOTH the reserved-field match
    and the alias detection, so the two can never disagree about what counts as
    the same key.
    """
    return "".join(ch for ch in key.lower() if ch.isalnum())


def reserved_fields_in(mapping: Mapping[str, Any]) -> tuple[str, ...]:
    """Reserved keys present at the top level of ``mapping``, in sorted order.

    Returns the keys as the SENDER spelled them, not normalized, so an error
    message names what was actually in the payload.
    """
    return tuple(sorted(key for key in mapping if normalize_key(key) in RESERVED_SECURITY_FIELDS))


def reject_reserved_fields(mapping: Mapping[str, Any]) -> None:
    """Refuse a payload that declares security-reserved state."""
    found = reserved_fields_in(mapping)
    if found:
        raise ReservedFieldRejected(found)


def reject_aliased_keys(mapping: Mapping[str, Any]) -> None:
    """Refuse a payload where two keys canonicalize to the same field."""
    seen: dict[str, str] = {}
    for key in mapping:
        canonical = normalize_key(key)
        first = seen.get(canonical)
        if first is not None:
            raise AmbiguousProtocolField(
                f"keys {first!r} and {key!r} both name the field {canonical!r}; "
                "a payload that states one field twice has no single meaning"
            )
        seen[canonical] = key


def guard_payload_keys(mapping: Mapping[str, Any]) -> None:
    """Both key-level defences, in the order that gives the better error.

    Aliasing is checked FIRST. ``policy_override`` beside ``policyOverride``
    should report the duplicate rather than the reserved name: the sender needs
    to know its message was self-contradictory before it learns the field was
    forbidden anyway.
    """
    reject_aliased_keys(mapping)
    reject_reserved_fields(mapping)
