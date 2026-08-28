"""The adapter type system, and the guarantees that are types rather than checks.

Most of Phase 8's security argument is that certain things cannot be
REPRESENTED. A check can be deleted in a refactor and nobody notices until an
attacker does; an absent enum member cannot be deleted, and an absent field
cannot be written to. These tests pin the absences, because an absence nobody
asserts is an absence somebody eventually fills in.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from packages.schemas.authorization import Authorization
from packages.schemas.capability import Capability
from packages.schemas.provenance import AuthorityLevel, TrustLevel
from pydantic import ValidationError
from services.adapters.errors import ADAPTER_REASON_CODES
from services.adapters.models import (
    FAMILY_PAYLOAD_TYPES,
    MAX_ADAPTER_AUTHORITY,
    OPERATION_CAPABILITY,
    PRIVILEGED_CAPABILITIES,
    TRANSLATING_FAMILIES,
    AdapterDescriptor,
    AdapterFamily,
    CandidateAuthorizationRequest,
    CandidateOperation,
    CandidateOperationType,
    SourceIdentity,
    SupportStatus,
    required_provenance_keys,
)


# --------------------------------------------------------------------------- #
# Source identity: unauthenticated by type
# --------------------------------------------------------------------------- #
def test_a_source_cannot_claim_to_be_authenticated():
    """``authenticated`` is Literal[False], so this fails validation.

    PACTRA authenticates no protocol channel. A boolean anybody could set is a
    boolean somebody eventually sets to True.
    """
    with pytest.raises(ValidationError):
        SourceIdentity(claimed_id="a", channel="c", authenticated=True)


def test_a_source_is_always_untrusted_at_agent_authority():
    source = SourceIdentity(claimed_id="anyone", channel="https")
    assert source.authenticated is False
    assert source.trust is TrustLevel.UNTRUSTED
    assert source.authority is AuthorityLevel.AGENT_PROPOSAL
    # This is what closes authority(output) <= authority(input): the input side
    # has no value above AGENT_PROPOSAL that it could take.
    assert source.authority <= MAX_ADAPTER_AUTHORITY


def test_source_identity_is_frozen():
    source = SourceIdentity(claimed_id="a", channel="c")
    with pytest.raises(ValidationError):
        source.claimed_id = "someone-else"


# --------------------------------------------------------------------------- #
# The privileged operation that does not exist
# --------------------------------------------------------------------------- #
def test_the_operation_enum_has_no_privileged_member():
    """The ``payment.execute`` answer, asserted rather than described.

    A tool call naming a privileged operation is not denied by a check — there
    is no canonical value it could map to.
    """
    values = {op.value for op in CandidateOperationType}
    forbidden = {
        "payment.execute",
        "refund.execute",
        "policy.modify",
        "authorization.issue",
        "merchant.modify",
    }
    assert not (values & forbidden)


def test_every_operation_maps_to_a_non_privileged_capability():
    """The second half: even a mapping mistake cannot reach a privileged one."""
    assert set(OPERATION_CAPABILITY) == set(CandidateOperationType)
    assert not (set(OPERATION_CAPABILITY.values()) & PRIVILEGED_CAPABILITIES)


def test_the_privileged_set_is_exactly_the_capabilities_denied_to_the_buyer_agent():
    """Kept in step with the kernel, so adding a privileged capability there
    without adding it here fails rather than silently widening what an adapter
    may require."""
    from packages.schemas.capability import buyer_agent_capabilities

    assert PRIVILEGED_CAPABILITIES == frozenset(buyer_agent_capabilities().deny)


def test_a_candidate_operation_cannot_declare_itself_authorized():
    with pytest.raises(ValidationError):
        CandidateOperation(
            candidate=False,
            operation=CandidateOperationType.OFFER_REQUEST,
            claimed_tool_name="x",
        )


def test_required_capability_is_a_property_not_a_field():
    """A field would be a place a payload could write."""
    assert "required_capability" not in CandidateOperation.model_fields
    candidate = CandidateOperation(
        operation=CandidateOperationType.PURCHASE_PROPOSE, claimed_tool_name="x"
    )
    assert candidate.required_capability is Capability.PAYMENT_PROPOSE


def test_a_candidate_operation_rejects_an_unknown_field():
    with pytest.raises(ValidationError):
        CandidateOperation(
            operation=CandidateOperationType.OFFER_REQUEST,
            claimed_tool_name="x",
            required_capability="payment.execute",
        )


# --------------------------------------------------------------------------- #
# The authorization artifact that cannot be built
# --------------------------------------------------------------------------- #
ARTIFACT_ONLY_FIELDS = frozenset(
    {
        "authorization_id",
        "nonce",
        "transaction_digest",
        "status",
        "consumed_at",
        "binding_version",
        "issued_at",
        "policy_version",
        "offer_version",
    }
)


def test_a_candidate_authorization_shares_no_artifact_field():
    """EXTERNAL AUTHORIZATION TOKEN != PACTRA AUTHORIZATION, as a type property.

    There is nothing to forge because there is no field to forge into.
    """
    candidate_fields = set(CandidateAuthorizationRequest.model_fields)
    artifact_fields = set(Authorization.model_fields)
    assert ARTIFACT_ONLY_FIELDS <= artifact_fields, "the artifact changed shape"
    assert not (candidate_fields & ARTIFACT_ONLY_FIELDS)


def test_a_candidate_authorization_cannot_declare_itself_non_candidate():
    with pytest.raises(ValidationError):
        CandidateAuthorizationRequest(
            candidate=False,
            claimed_merchant_id="m",
            claimed_product_id="p",
            claimed_quantity=1,
            claimed_amount_inr=1,
            claimed_currency="INR",
        )


@pytest.mark.parametrize("amount", ["3799", 3799.0, True, None])
def test_money_is_never_coerced_at_the_boundary(amount):
    """StrictInt. A protocol boundary is where lax coercion decides an amount."""
    with pytest.raises(ValidationError):
        CandidateAuthorizationRequest(
            claimed_merchant_id="m",
            claimed_product_id="p",
            claimed_quantity=1,
            claimed_amount_inr=amount,
            claimed_currency="INR",
        )


def test_a_naive_expiry_is_refused():
    with pytest.raises(ValidationError):
        CandidateAuthorizationRequest(
            claimed_merchant_id="m",
            claimed_product_id="p",
            claimed_quantity=1,
            claimed_amount_inr=1,
            claimed_currency="INR",
            claimed_expires_at=datetime(2030, 1, 1, 12, 0, 0),
        )


def test_currency_folds_but_merchant_identity_does_not():
    """Currency is case-insensitive by domain convention; identity is not.

    Folding an identity would turn a case variant into a MATCH. Leaving it
    exact means a case variant simply fails to match the authenticated id,
    which is the correct outcome.
    """
    candidate = CandidateAuthorizationRequest(
        claimed_merchant_id="Merchant_A",
        claimed_product_id="P1",
        claimed_quantity=1,
        claimed_amount_inr=1,
        claimed_currency="inr",
        claimed_expires_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
    )
    assert candidate.claimed_currency == "INR"
    assert candidate.claimed_merchant_id == "Merchant_A"
    assert candidate.claimed_merchant_id != "merchant_a"


def test_a_candidate_authorization_is_frozen():
    candidate = CandidateAuthorizationRequest(
        claimed_merchant_id="m",
        claimed_product_id="p",
        claimed_quantity=1,
        claimed_amount_inr=3799,
        claimed_currency="INR",
    )
    with pytest.raises(ValidationError):
        candidate.claimed_amount_inr = 4399


def test_a_mission_id_is_a_uuid_and_not_a_grant():
    candidate = CandidateAuthorizationRequest(
        mission_id=str(uuid.uuid4()),
        claimed_merchant_id="m",
        claimed_product_id="p",
        claimed_quantity=1,
        claimed_amount_inr=1,
        claimed_currency="INR",
    )
    assert isinstance(candidate.mission_id, uuid.UUID)


# --------------------------------------------------------------------------- #
# Descriptors: ceilings enforced at construction
# --------------------------------------------------------------------------- #
def _descriptor(**overrides) -> AdapterDescriptor:
    base = dict(
        adapter_id="test.adapter.v1",
        family=AdapterFamily.TOOL,
        protocol_name="test",
        protocol_version="1.0",
        supported_protocol_versions=("1.0",),
        adapter_version="test-1",
        status=SupportStatus.IMPLEMENTED,
        summary="A descriptor used only by the adapter type tests.",
    )
    base.update(overrides)
    return AdapterDescriptor(**base)


@pytest.mark.parametrize(
    "authority",
    [
        AuthorityLevel.TRUSTED_INTERNAL_SERVICE,
        AuthorityLevel.AUTHORIZATION,
        AuthorityLevel.SYSTEM_SECURITY_POLICY,
        AuthorityLevel.USER_POLICY,
    ],
)
def test_a_descriptor_cannot_declare_authority_above_the_ceiling(authority):
    with pytest.raises(ValidationError):
        _descriptor(emits_authority=authority)


@pytest.mark.parametrize("trust", [TrustLevel.TRUSTED, TrustLevel.AUTHORITATIVE])
def test_a_descriptor_cannot_declare_trusted_output(trust):
    with pytest.raises(ValidationError):
        _descriptor(emits_trust=trust)


def test_a_descriptor_primary_version_must_be_in_its_supported_set():
    with pytest.raises(ValidationError):
        _descriptor(protocol_version="2.0", supported_protocol_versions=("1.0",))


def test_a_descriptor_is_frozen():
    descriptor = _descriptor()
    with pytest.raises(ValidationError):
        descriptor.status = SupportStatus.PLANNED


def test_supports_is_exact_membership_not_a_prefix_match():
    descriptor = _descriptor(supported_protocol_versions=("1.0", "1.1"), protocol_version="1.0")
    assert descriptor.supports("1.0")
    assert not descriptor.supports("1.0.1")
    assert not descriptor.supports("1")
    assert not descriptor.supports("*")


# --------------------------------------------------------------------------- #
# Families
# --------------------------------------------------------------------------- #
def test_every_family_has_a_display_name():
    for family in AdapterFamily:
        assert family.display_name.endswith("Adapter")


def test_only_translating_families_declare_payload_types():
    """A family with no payload type cannot emit an envelope at all."""
    assert set(FAMILY_PAYLOAD_TYPES) == set(TRANSLATING_FAMILIES)
    assert AdapterFamily.PAYMENT_RAIL not in TRANSLATING_FAMILIES
    assert AdapterFamily.AGENT_COMMUNICATION not in TRANSLATING_FAMILIES


def test_no_two_payload_types_are_shared_between_families():
    """Otherwise the family/payload check could not distinguish them."""
    seen: dict[type, AdapterFamily] = {}
    for family, types in FAMILY_PAYLOAD_TYPES.items():
        for payload_type in types:
            assert payload_type not in seen, (
                f"{payload_type.__name__} is claimed by both {seen.get(payload_type)} and {family}"
            )
            seen[payload_type] = family


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #
def test_every_adapter_error_has_a_distinct_reason_code():
    """A shared code would make two different refusals report identically, and
    the attack lab scores scenarios against these codes."""
    assert len(ADAPTER_REASON_CODES) == len(set(ADAPTER_REASON_CODES))


def test_every_reason_code_is_namespaced():
    for code in ADAPTER_REASON_CODES:
        assert code.startswith("ADAPTER_"), code
        assert code.isupper()


# --------------------------------------------------------------------------- #
# Provenance completeness
# --------------------------------------------------------------------------- #
def test_a_payload_type_without_a_completeness_rule_is_refused():
    """Silence here would mean "requires no provenance at all".

    ``required_provenance_keys`` is what makes provenance coverage enforceable,
    so a canonical payload type added without a rule must fail loudly. Returning
    an empty set instead would let the next payload type ship with no provenance
    obligation and no test noticing.
    """
    with pytest.raises(TypeError, match="no provenance-completeness rule"):
        required_provenance_keys(object())


def test_the_rule_names_optional_values_only_once_they_are_present():
    """A key demanded for an absent value would push adapters into inventing
    entries, which is the opposite of what provenance is for."""
    base = dict(
        claimed_merchant_id="merchant_a",
        claimed_product_id="P1",
        claimed_quantity=1,
        claimed_amount_inr=3799,
        claimed_currency="INR",
    )
    bare = required_provenance_keys(CandidateAuthorizationRequest(**base))
    assert "external_authorization_reference" not in bare
    assert "untrusted_metadata" not in bare

    filled = required_provenance_keys(
        CandidateAuthorizationRequest(
            **base,
            external_authorization_reference="ext-ref",
            untrusted_metadata={"unknown": "kept"},
        )
    )
    assert "external_authorization_reference" in filled
    assert "untrusted_metadata" in filled
