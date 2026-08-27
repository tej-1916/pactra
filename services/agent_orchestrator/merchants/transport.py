"""Merchant transport — where merchant identity is established.

The transport is the trust boundary for *who the merchant is*. It derives a
``MerchantIdentity`` from the connection it holds (in Phase 2: the server-side
adapter registration) and binds it to the server-owned reputation record before
any payload is read. Downstream code therefore receives offers already paired
with an identity it did not have to infer from merchant-controlled data.

Honest scoping: ``IN_PROCESS_ADAPTER`` is not cryptographic authentication.
Phase 2 has no signing or mutual TLS; identity is trusted because it comes from
server-side registration rather than from the wire. Real cryptographic merchant
authentication is Phase 3 work and is not claimed here.
"""

from __future__ import annotations

from packages.schemas.domain import MissionConstraints
from packages.schemas.invariants import require
from packages.schemas.merchant import (
    AuthenticatedQuote,
    MerchantAuthMethod,
    MerchantContext,
    MerchantIdentity,
)

from services.agent_orchestrator.merchants.base import MerchantAgent
from services.security_kernel.merchant_registry import MerchantRegistry, default_merchant_registry

CHANNEL = "in-process"


class MerchantTransport:
    def __init__(self, registry: MerchantRegistry | None = None) -> None:
        self.registry = registry or default_merchant_registry()

    def connect(self, agent: MerchantAgent) -> MerchantContext:
        """Establish the trusted context for one merchant connection.

        The identity comes from the adapter registration; nothing the merchant
        later returns can change it.
        """
        registered_id = agent.merchant_id
        require(
            bool(registered_id) and bool(registered_id.strip()),
            "merchant.connection_has_identity",
            "merchant adapter has no transport-level registration id",
        )
        identity = MerchantIdentity(
            merchant_id=registered_id,
            auth_method=MerchantAuthMethod.IN_PROCESS_ADAPTER,
            channel=CHANNEL,
        )
        return self.registry.context_for(identity)

    def collect(
        self,
        agents: list[MerchantAgent],
        constraints: MissionConstraints,
        quantity: int,
    ) -> list[AuthenticatedQuote]:
        """Query every merchant, keeping each response bound to the identity
        that produced it. Responses are never flattened into one anonymous list."""
        quotes: list[AuthenticatedQuote] = []
        for agent in agents:
            context = self.connect(agent)
            quotes.append(
                AuthenticatedQuote(context=context, offers=agent.quote(constraints, quantity))
            )
        return quotes
