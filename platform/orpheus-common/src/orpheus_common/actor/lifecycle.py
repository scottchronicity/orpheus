"""Lifecycle glue — signal handling shared by the agents (ADR 0017 actor model)."""

from __future__ import annotations

import asyncio
import signal
from typing import Iterable

from orpheus_common.logging import get_logger

logger = get_logger(__name__)

_DEFAULT_SIGNALS = (signal.SIGINT, signal.SIGTERM)


def install_signal_handlers(
    loop: asyncio.AbstractEventLoop,
    stop_event: asyncio.Event,
    signals: Iterable[signal.Signals] = _DEFAULT_SIGNALS,
) -> None:
    """Wire SIGINT/SIGTERM to set ``stop_event`` — the agents' shutdown trigger.

    Tolerant of contexts where a loop can't take signal handlers (a non-main
    thread, e.g. an in-process test/sim harness): it logs and skips instead of
    raising, so the same ``start()`` path runs in production and under test
    without monkeypatching.
    """
    for sig in signals:
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except (NotImplementedError, RuntimeError, ValueError) as e:
            logger.warning(
                "Could not install signal handler (non-main-thread?)",
                signal=getattr(sig, "name", str(sig)),
                error=str(e),
            )
