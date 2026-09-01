"""PeriodicTask — run a callback every N seconds against an injectable Clock.

The per-agent heartbeat and any other periodic work become a ``PeriodicTask`` with
a configurable interval and a ``Clock`` (ADR 0017 actor model). With ``WallClock``
the cadence is real (default, unchanged); with ``ManualClock`` it's deterministic
and instant in tests/sim. Replaces the hardcoded ``while True: asyncio.sleep(30)``
heartbeat loops the agents hand-roll today.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Awaitable, Callable, Optional, Union

from orpheus_common.actor.clock import Clock, WallClock
from orpheus_common.logging import get_logger

logger = get_logger(__name__)

# A periodic callback: sync, or async (returns an awaitable).
PeriodicFn = Callable[[], Union[None, Awaitable[None]]]


class PeriodicTask:
    """Invoke ``fn`` every ``interval`` seconds (of ``clock``'s time) until
    stopped. A callback exception is logged and the loop continues — one bad tick
    never kills the cadence. Sleeps first, then calls (so the first call is one
    interval in, matching the agents' heartbeat semantics)."""

    def __init__(
        self,
        interval: float,
        fn: PeriodicFn,
        *,
        clock: Optional[Clock] = None,
        name: str = "periodic",
    ) -> None:
        self._interval = float(interval)
        self._fn = fn
        self._clock = clock or WallClock()
        self._name = name
        self._task: Optional[asyncio.Task] = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        """Schedule the loop on the running event loop (idempotent)."""
        if self.running:
            return
        self._task = asyncio.ensure_future(self._run())

    async def _run(self) -> None:
        try:
            while True:
                await self._clock.sleep(self._interval)
                try:
                    result = self._fn()
                    if asyncio.iscoroutine(result):
                        await result
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Periodic task callback failed", task=self._name)
        except asyncio.CancelledError:
            raise

    async def stop(self) -> None:
        """Cancel the loop and await its unwind (idempotent)."""
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None
