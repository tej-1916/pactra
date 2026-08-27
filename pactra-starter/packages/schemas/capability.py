"""Capability types. Enforcement lives in services/security_kernel/capability.py."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class Capability(str, Enum):
    CATALOG_READ = "catalog.read"
    MERCHANT_DISCOVER = "merchant.discover"
    OFFER_REQUEST = "offer.request"
    OFFER_RANK = "offer.rank"
    PAYMENT_PROPOSE = "payment.propose"
    # Privileged — denied to buyer agents:
    PAYMENT_EXECUTE = "payment.execute"
    REFUND_EXECUTE = "refund.execute"
    POLICY_MODIFY = "policy.modify"
    AUTHORIZATION_ISSUE = "authorization.issue"
    MERCHANT_MODIFY = "merchant.modify"


class CapabilitySet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    principal: str
    allow: set[Capability] = Field(default_factory=set)
    deny: set[Capability] = Field(default_factory=set)
    limits: dict = Field(default_factory=dict)


def buyer_agent_capabilities(principal: str = "buyer-agent") -> CapabilitySet:
    return CapabilitySet(
        principal=principal,
        allow={
            Capability.CATALOG_READ,
            Capability.MERCHANT_DISCOVER,
            Capability.OFFER_REQUEST,
            Capability.OFFER_RANK,
            Capability.PAYMENT_PROPOSE,
        },
        deny={
            Capability.PAYMENT_EXECUTE,
            Capability.REFUND_EXECUTE,
            Capability.POLICY_MODIFY,
            Capability.AUTHORIZATION_ISSUE,
            Capability.MERCHANT_MODIFY,
        },
        limits={"single_transaction_inr": 4500, "daily_inr": 10000},
    )
