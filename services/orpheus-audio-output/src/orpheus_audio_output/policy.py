"""Reconnect policy: capped exponential backoff and log throttling."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .config import ReconnectConfig


@dataclass
class Backoff:
    """Per-responsibility retry schedule.

    ``initial_delay_seconds`` after the first failure, doubling per consecutive
    failure up to ``max_delay_seconds``. With ``reconnect.enabled`` false, only
    the first attempt is made; afterwards the state is reported, not retried.
    """

    policy: ReconnectConfig
    failures: int = 0
    next_attempt: float = 0.0
    attempts: int = 0

    def due(self, now: float) -> bool:
        if not self.policy.enabled and self.attempts > 0:
            return False
        return now >= self.next_attempt

    def delay(self) -> float:
        if self.failures <= 0:
            return self.policy.initial_delay_seconds
        # Cap the exponent: a week-long outage must not overflow a float.
        delay = self.policy.initial_delay_seconds * (2 ** min(self.failures - 1, 30))
        return min(delay, self.policy.max_delay_seconds)

    def success(self, now: float) -> None:
        self.attempts += 1
        self.failures = 0
        self.next_attempt = now

    def failure(self, now: float) -> float:
        self.attempts += 1
        self.failures += 1
        wait = self.delay()
        self.next_attempt = now + wait
        return wait


class LogThrottle:
    """Logs a (key, message) when it changes, and repeats an unchanged failure
    at most every ``repeat_seconds``, so a week-long outage costs a handful of
    lines rather than thousands."""

    def __init__(self, repeat_seconds: float = 600.0) -> None:
        self.repeat_seconds = repeat_seconds
        self._last: dict[str, tuple[str, float, int]] = {}

    def should_log(self, key: str, message: str, now: float) -> tuple[bool, int]:
        """Returns (log it?, how many identical reports were suppressed)."""
        last: Optional[tuple[str, float, int]] = self._last.get(key)
        if last is None or last[0] != message:
            self._last[key] = (message, now, 0)
            return True, 0
        text, when, suppressed = last
        if now - when >= self.repeat_seconds:
            self._last[key] = (text, now, 0)
            return True, suppressed
        self._last[key] = (text, when, suppressed + 1)
        return False, suppressed + 1

    def clear(self, key: str) -> None:
        self._last.pop(key, None)
