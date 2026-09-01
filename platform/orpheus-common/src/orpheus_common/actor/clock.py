"""Injectable time source — the tick/clock seam for the actor model (ADR 0017).

Agents tick at configurable frequencies (heartbeats, periodic work). In production
that's wall-clock time; in tests and the Simulacrum we want those ticks to be
deterministic and instant rather than waiting real seconds. So time is a seam:

- ``WallClock`` — real time (the default everywhere, so production behavior is
  byte-identical to hardcoded ``asyncio.sleep``).
- ``ManualClock`` — virtual time the caller advances; ``sleep`` resolves when the
  clock passes the deadline. Lets a test assert "two heartbeats elapsed" in
  microseconds, and a sim run a day of collective behavior in seconds.

Built clean for OSS — a small, dependency-free abstraction.
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import List, Tuple


class Clock(ABC):
    """A time source: wall-clock ``now()``, a ``monotonic()`` counter for
    intervals, and an awaitable ``sleep()``."""

    @abstractmethod
    def now(self) -> datetime:
        """Current wall-clock time (timezone-aware, UTC)."""

    @abstractmethod
    def monotonic(self) -> float:
        """A monotonic seconds counter (for measuring intervals, not dates)."""

    @abstractmethod
    async def sleep(self, seconds: float) -> None:
        """Suspend for ``seconds`` of this clock's time."""


class WallClock(Clock):
    """Real time. The default — production behaves exactly as before."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def monotonic(self) -> float:
        return time.monotonic()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


class ManualClock(Clock):
    """Virtual, advanceable time for tests + the Simulacrum.

    ``sleep(s)`` registers a waiter at ``monotonic()+s`` and blocks until
    ``advance()`` pushes virtual time past it — so periodic behavior is
    deterministic and runs as fast as the caller advances the clock. Drive it from
    the event loop the sleepers run on (yield with ``await asyncio.sleep(0)`` after
    ``advance`` to let released coroutines proceed)."""

    def __init__(self, start: float = 0.0) -> None:
        self._t = float(start)
        self._waiters: List[Tuple[float, asyncio.Event]] = []

    def now(self) -> datetime:
        return datetime.fromtimestamp(self._t, tz=timezone.utc)

    def monotonic(self) -> float:
        return self._t

    async def sleep(self, seconds: float) -> None:
        if seconds <= 0:
            return
        event = asyncio.Event()
        self._waiters.append((self._t + seconds, event))
        await event.wait()

    def advance(self, seconds: float) -> None:
        """Advance virtual time, releasing every sleep whose deadline has passed."""
        self._t += float(seconds)
        remaining: List[Tuple[float, asyncio.Event]] = []
        for deadline, event in self._waiters:
            if deadline <= self._t:
                event.set()
            else:
                remaining.append((deadline, event))
        self._waiters = remaining
