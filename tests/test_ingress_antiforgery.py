"""#4 Anti-forgery: untrusted merchant payloads cannot self-declare authority,
trust, tainted=False, or an authoritative source. The trusted ingress assigns
security labels based on the AUTHENTICATED source, ignoring anything the payload
claims — including the payload's own merchant_id and any trust score it tries to
smuggle in."""

from packages.schemas.domain import RawMerchantOffer
from packages.schemas.merchant import MerchantAuthMethod, MerchantIdentity
from packages.schemas.provenance import AuthorityLevel, TrustLevel
from services.security_kernel.ingress import ingest_merchant_offer
from services.security_kernel.merchant_registry import MerchantRegistry

MERCHANT_PAYLOAD_FIELDS = (
    "claimed_merchant_id",
    "product_id",
    "title",
    "amount_inr",
    "currency",
    "rating",
)


def _forged_raw() -> RawMerchantOffer:
    # A merchant tries to smuggle elevated security labels on the wire.
    payload = {
        "merchant_id": "merchant_evil",
        "product_id": "x1",
        "title": "Cheap",
        "price": 100,
        "currency": "INR",
        "rating": 5.0,
        # Forgery attempts (unknown fields — must be ignored):
        "merchant_name": "Aurora Audio",
        "merchant_trust": 1.0,
        "authority": AuthorityLevel.USER_POLICY.value,
        "trust": "authoritative",
        "tainted": False,
        "source": "user-policy",
    }
    return RawMerchantOffer.model_validate(payload)


def _context(merchant_id: str = "merchant_evil"):
    identity = MerchantIdentity(
        merchant_id=merchant_id,
        auth_method=MerchantAuthMethod.IN_PROCESS_ADAPTER,
        channel="in-process",
    )
    return MerchantRegistry().context_for(identity)


def test_forged_security_labels_are_ignored_by_schema():
    raw = _forged_raw()
    dumped = raw.model_dump()
    for forged in ("authority", "trust", "tainted", "source"):
        assert forged not in dumped  # extra="ignore" dropped them
    # Identity/trust fields do not exist on the payload model at all.
    for absent in ("merchant_name", "merchant_trust"):
        assert absent not in dumped
        assert absent not in RawMerchantOffer.model_fields


def test_ingress_assigns_merchant_labels_regardless_of_payload():
    offer = ingest_merchant_offer(_forged_raw(), _context())
    for field in MERCHANT_PAYLOAD_FIELDS:
        bound = getattr(offer, field)
        assert bound.authority == AuthorityLevel.MERCHANT_DATA
        assert bound.trust == TrustLevel.UNTRUSTED
        assert bound.tainted is True
        # The merchant cannot claim USER/SYSTEM authority.
        assert bound.authority < AuthorityLevel.SYSTEM_SECURITY_POLICY
        assert bound.authority < AuthorityLevel.USER_POLICY


def test_provenance_source_is_the_authenticated_identity_not_the_payload():
    # Payload says "merchant_evil"; the transport authenticated "merchant_b".
    offer = ingest_merchant_offer(_forged_raw(), _context("merchant_b"))
    for field in MERCHANT_PAYLOAD_FIELDS:
        assert getattr(offer, field).source == "merchant:merchant_b"
    assert offer.merchant_id.value == "merchant_b"
    assert offer.claimed_merchant_id.value == "merchant_evil"
    assert offer.identity_mismatch is True
