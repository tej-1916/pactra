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


def security_kernel_capabilities(principal: str = "security-kernel") -> CapabilitySet:
    """The ONLY principal permitted to mint authorizations (Phase 3).

    Authorization issuance is deliberately split away from the buyer agent. The
    buyer agent — the principal an LLM or a compromised agent acts through —
    explicitly denies ``authorization.issue``, so no amount of agent compromise
    can mint an authorization: **LLM OUTPUT -> NEVER AUTHORIZATION**.

    The kernel principal is not a superuser. It may issue authorizations and
    propose payments; it is still denied ``payment.execute``, ``refund.execute``
    and ``policy.modify``, so an authorization can be created but never
    self-executed, and the kernel cannot rewrite the policy it enforces.
    """
    return CapabilitySet(
        principal=principal,
        allow={
            Capability.AUTHORIZATION_ISSUE,
            Capability.PAYMENT_PROPOSE,
        },
        deny={
            Capability.PAYMENT_EXECUTE,
            Capability.REFUND_EXECUTE,
            Capability.POLICY_MODIFY,
            Capability.MERCHANT_MODIFY,
        },
    )


def payment_executor_capabilities(principal: str = "payment-executor") -> CapabilitySet:
    """The ONLY principal permitted to execute a payment (Phase 4).

    ``payment.execute`` is deliberately held by nobody else. It is denied to
    ``buyer-agent`` — the principal an LLM or a compromised agent acts through —
    and also denied to ``security-kernel``, which mints authorizations. That
    second denial is the important one: it means the component that can CREATE
    an authorization cannot also SPEND it, so compromising the issuing path
    still does not move money.

    This principal is not a superuser either. It may execute and propose
    payments; it is still denied ``authorization.issue``, so the executor cannot
    manufacture the authorization it requires, and denied ``policy.modify`` and
    ``merchant.modify``, so it cannot rewrite the rules it is executing under.
    The result is a genuine separation of duties: issuing, spending, and
    policy-setting are three different principals, and no single compromise
    spans them.
    """
    return CapabilitySet(
        principal=principal,
        allow={
            Capability.PAYMENT_EXECUTE,
            Capability.PAYMENT_PROPOSE,
        },
        deny={
            Capability.AUTHORIZATION_ISSUE,
            Capability.REFUND_EXECUTE,
            Capability.POLICY_MODIFY,
            Capability.MERCHANT_MODIFY,
        },
    )
