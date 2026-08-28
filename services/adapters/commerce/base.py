"""``CommerceAdapter`` — the merchant / catalog / offer boundary.

WHAT A COMMERCE ADAPTER DOES
    ingest an external merchant, catalog, or offer document; validate its
    protocol structure; normalize it into PACTRA's existing untrusted merchant
    schema; keep the merchant's SELF-ASSERTED identity as a claim; preserve
    provenance and taint; refuse malformed input.

WHAT IT CANNOT DO, STRUCTURALLY RATHER THAN BY RULE
    * **Assign merchant trust.** Its output type has no trust field and no
      ``MerchantContext``, and this package does not import
      ``MerchantRegistry``. Trust reaches an offer only through
      ``ingest_merchant_offer(raw, context)``, whose context comes from
      ``MerchantTransport``. An adapter holds nothing to assign trust from.
    * **Authenticate a merchant.** ``SourceIdentity.authenticated`` is
      ``Literal[False]``. The claimed merchant id is compared against a
      transport-authenticated identity downstream, exactly as a Phase 2 payload
      claim is, and a mismatch is ``MERCHANT_IDENTITY_MISMATCH``.
    * **Alter protected policy.** ``guard_payload_keys`` refuses a top-level
      ``hard_limit_inr`` or ``min_merchant_trust``; a claim nested in
      ``RawMerchantOffer.claims`` is left for the authority lattice, which
      already refuses it and writes a ``SECURITY_VIOLATION``.
    * **Authorize or execute anything.** ``translate_payload`` is a synchronous
      pure function with no session parameter. There is nothing it could write
      through.

STRICTER THAN THE MODEL IT PRODUCES, ON PURPOSE
    ``RawMerchantOffer`` uses Pydantic's lax mode, so ``price="3799"`` would
    coerce. That is acceptable for a trusted caller constructing the model
    in-process and is not acceptable at a protocol boundary, where the sender
    chose the type. Concrete adapters therefore check JSON types themselves
    before constructing the model. The DTO is unchanged: tightening it would
    change Phase 1 behaviour for every existing caller to fix a problem that
    only exists here.
"""

from __future__ import annotations

import abc

from services.adapters.models import (
    AdapterDescriptor,
    AdapterFamily,
    AdapterWarning,
    CandidateCommerceCatalog,
    CandidateCommerceOffer,
    SourceIdentity,
)
from services.adapters.translation import TranslationResult

FAMILY = AdapterFamily.COMMERCE


class CommerceAdapter(abc.ABC):
    """Base class for every commerce-protocol adapter.

    Concrete adapters implement ``translate_payload`` only. Envelope
    construction, the authority-ceiling check, the taint check and the
    family/payload-type check all live in ``services.adapters.translate`` — so
    an adapter cannot exempt itself from them by forgetting to call something.
    """

    #: Set by the concrete subclass; the registry re-checks that its family
    #: matches the descriptor it is registered under.
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
    ) -> TranslationResult[CandidateCommerceCatalog | CandidateCommerceOffer]:
        """Parse one external commerce document into candidate commerce data.

        Raises an ``AdapterError`` subclass on anything malformed, reserved, or
        ambiguous. Returns a ``TranslationResult`` carrying the canonical
        payload, its per-field provenance, and any warnings.
        """
        raise NotImplementedError


__all__ = [
    "FAMILY",
    "AdapterWarning",
    "CandidateCommerceCatalog",
    "CandidateCommerceOffer",
    "CommerceAdapter",
]
