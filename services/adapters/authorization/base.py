"""``PaymentAuthorizationAdapter`` — the most dangerous family, so the narrowest.

THE INVARIANT THIS FAMILY EXISTS TO PRESERVE
    EXTERNAL AUTHORIZATION TOKEN  !=  PACTRA AUTHORIZATION

An external system saying "this purchase is authorized" is an external system's
opinion. PACTRA's authorization is an artifact minted by ``issue_authorization``
under the ``authorization.issue`` capability, bound to a transaction digest,
carrying a server-held nonce, and consumable exactly once by a conditional
UPDATE. The two are not the same kind of thing and the gap between them is not
bridgeable by parsing.

Bridging it would need protocol-specific cryptographic trust, and PACTRA has
none. The USER_ED25519 verifier accepts only a server-built PACTRA challenge
under the pre-enrolled demo key; it does not validate arbitrary external
authorization artifacts or create a ``VERIFIED_USER_POLICY`` authority level.
So this family produces a ``CandidateAuthorizationRequest`` and the flow
continues through the controls that already exist:

    external authorization representation
        -> adapter parsing
        -> CandidateAuthorizationRequest
        -> transaction binding validation
        -> deterministic policy
        -> server authorization issuer  (security-kernel principal)
        -> PACTRA AuthorizationArtifact

WHY THE OUTPUT TYPE IS THE ENFORCEMENT
    ``CandidateAuthorizationRequest`` has no nonce, no transaction digest, no
    authorization id, no status and no ``consumed_at``. There is nothing to
    forge because there is no field to forge into, and no function in this
    package constructs an ``Authorization`` or an ``AuthorizationRow`` —
    ``tests/test_adapter_isolation.py`` parses the import graph and fails if one
    ever could.

    ``external_authorization_reference`` is carried as an opaque string and
    every envelope containing one gets an
    ``EXTERNAL_AUTHORIZATION_REFERENCE_NOT_VERIFIED`` warning. Carrying it
    unverified and saying so is honest; carrying it and treating it as evidence
    would be the failure this whole phase is written against.

AP2
    This family is where an AP2 adapter would live. It does not exist. No AP2
    message schema is documented in this repository, and inventing one would be
    a fake integration. See ``services/adapters/support.py``.
"""

from __future__ import annotations

import abc

from services.adapters.models import (
    AdapterDescriptor,
    AdapterFamily,
    CandidateAuthorizationRequest,
    SourceIdentity,
)
from services.adapters.translation import TranslationResult

FAMILY = AdapterFamily.PAYMENT_AUTHORIZATION


class PaymentAuthorizationAdapter(abc.ABC):
    """Base class for every payment-authorization protocol adapter."""

    descriptor: AdapterDescriptor

    @property
    def family(self) -> AdapterFamily:
        return FAMILY

    @abc.abstractmethod
    def translate_payload(
        self,
        payload: object,
        *,
        source: SourceIdentity,
        protocol_version: str,
    ) -> TranslationResult[CandidateAuthorizationRequest]:
        """Parse an external authorization representation into a CANDIDATE.

        Never returns anything a downstream component could consume. The only
        way to reach a real authorization from here is the full kernel path.
        """
        raise NotImplementedError


__all__ = [
    "FAMILY",
    "CandidateAuthorizationRequest",
    "PaymentAuthorizationAdapter",
]
