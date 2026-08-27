"""Runnable outbox worker.

    python -m services.payment_executor.run_worker --provider fake

This is the ONLY process that reaches a payment provider. It is deliberately a
separate entrypoint from the API rather than a background task inside it: a
worker embedded in the web process would be reachable from request-handling
code, and the guarantee that "no code reachable from an HTTP request talks to a
payment rail" would become a convention instead of a structural fact.

The loop is intentionally dull. Every property that makes it safe already lives
in the code it calls — the claim is atomic, the lease survives a crash, and each
handler is idempotent — so the loop adds no cleverness of its own. Idle polling
sleeps rather than spinning; an unexpected handler error is logged and the loop
continues, because the event has already been rescheduled with backoff by
``run_once`` and stopping the worker would strand every other payment.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import signal

from apps.api.db.session import get_sessionmaker
from apps.api.pactra.config import get_settings

from services.payment_executor.registry import (
    ProviderUnavailable,
    UnknownProvider,
    provider_for,
    registered_provider_names,
)
from services.payment_executor.worker import run_once

LOGGER = logging.getLogger("pactra.payment_worker")

#: How long to wait when the queue is empty. Short enough that a queued payment
#: is not perceptibly delayed; long enough that an idle worker is not a busy
#: loop against the database.
IDLE_SLEEP_SECONDS = 0.5


async def run_forever(
    *,
    provider_name: str,
    worker_id: str,
    app_env: str,
    stop: asyncio.Event,
) -> int:
    """Drain the outbox until ``stop`` is set. Returns the events processed."""
    provider = provider_for(provider_name, app_env=app_env)
    sessionmaker = get_sessionmaker()
    processed = 0

    LOGGER.info("worker %s started for provider %s", worker_id, provider_name)
    while not stop.is_set():
        try:
            outcome = await run_once(sessionmaker, provider=provider, worker_id=worker_id)
        except Exception:  # noqa: BLE001
            # run_once has already returned the event to the queue with backoff
            # in its own transaction. Exiting here would strand every OTHER
            # payment for the sake of one bad event, so the loop continues.
            LOGGER.exception("worker %s: handler failed; event rescheduled", worker_id)
            await _sleep_or_stop(stop, IDLE_SLEEP_SECONDS)
            continue

        if outcome.event_id is None:
            await _sleep_or_stop(stop, IDLE_SLEEP_SECONDS)
            continue

        processed += 1
        LOGGER.info(
            "worker %s processed %s (%s) -> %s",
            worker_id,
            outcome.event_id,
            outcome.event_type,
            outcome.result.state.value if outcome.result else "n/a",
        )

    LOGGER.info("worker %s stopped after %d events", worker_id, processed)
    return processed


async def _sleep_or_stop(stop: asyncio.Event, seconds: float) -> None:
    """Sleep, but wake immediately on shutdown rather than after the full nap."""
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=seconds)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="PACTRA payment outbox worker")
    parser.add_argument(
        "--provider",
        default="fake" if settings.app_env != "production" else "razorpay_test",
        choices=list(registered_provider_names(app_env=settings.app_env)),
    )
    parser.add_argument("--worker-id", default="worker-1")
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args(argv)


async def _amain(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        # Graceful: the in-flight event finishes and commits. Killing mid-call
        # is survivable too — that is what the lease is for — but it is not the
        # behaviour a deliberate shutdown should choose.
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)

    try:
        await run_forever(
            provider_name=args.provider,
            worker_id=args.worker_id,
            app_env=get_settings().app_env,
            stop=stop,
        )
    except (UnknownProvider, ProviderUnavailable) as exc:
        LOGGER.error("cannot start: %s", exc)
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_amain(argv))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
