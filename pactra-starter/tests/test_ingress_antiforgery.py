"""#4 Anti-forgery: untrusted merchant payloads cannot self-declare authority,
trust, tainted=False, or an authoritative source. The trusted ingress assigns
security labels based on the source, ignoring anything the payload claims."""

from packages.schemas.domain import RawMerchantOffer
from packages.schemas.provenance import AuthorityLevel, TrustLevel
from services.security_kernel.ingress import ingest_merchant_offer


def _forged_raw() -> RawMerchantOffer:
    # A merchant tries to smuggle elevated security labels on the wire.
    payload = {
        "merchant_id": "merchant_evil",
        "merchant_name": "Evil Co",
        "product_id": "x1",
        "title": "Cheap",
        "price": 100,
        "currency": "INR",
        "rating": 5.0,
        # Forgery attempts (unknown fields — must be ignored):
        "authority": AuthorityLevel.USER_SIGNED_POLICY.value,
        "trust": "authoritative",
        "tainted": False,
        "source": "user-policy",
    }
    return RawMerchantOffer.model_validate(payload)


def test_forged_security_labels_are_ignored_by_schema():
    raw = _forged_raw()
    dumped = raw.model_dump()
    for forged in ("authority", "trust", "tainted", "source"):
        assert forged not in dumped  # extra="ignore" dropped them


def test_ingress_assigns_merchant_labels_regardless_of_payload():
    offer = ingest_merchant_offer(_forged_raw())
    for field in ("merchant_id", "amount_inr", "rating", "title", "currency"):
        bound = getattr(offer, field)
        assert bound.authority == AuthorityLevel.MERCHANT_DATA
        assert bound.trust == TrustLevel.UNTRUSTED
        assert bound.tainted is True
        # The merchant cannot claim USER/SYSTEM authority.
        assert bound.authority < AuthorityLevel.SYSTEM_SECURITY_POLICY
        assert bound.authority < AuthorityLevel.USER_SIGNED_POLICY
