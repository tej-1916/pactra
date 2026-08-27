"""Payment executor — PRIVILEGED INFRASTRUCTURE (Phase 4).

Nothing in this package may be reached from agent- or LLM-controlled code. The
gate is the capability firewall: ``payment.execute`` is held only by the
``payment-executor`` principal and is explicitly DENIED to ``buyer-agent`` and
to ``security-kernel``. Every entry point that consumes an authorization or
speaks to a provider enforces it before touching state.

Call order is fixed and is the reason the reliability properties hold:

    request  ->  intents.create_payment_intent    (one DB transaction, COMMIT)
                     |
                     +-- consume authorization, write intent, audit, outbox
                     v
             outbox worker  ->  executor.dispatch  ->  PaymentProvider
                     |
                     +-- uncertain? -> reconciliation converges the state

The provider is never called before the intent and its outbox row are durable,
and never from the request path.
"""
