"""State-space latent memory: temporal likelihood over entity history.

[CORE] State Space Likelihood & Latent Memory (Epic 1). Lets agents ask "how
likely is a coyote at 02:00?" from accumulated history, so the system can
pre-position attention instead of only reacting. SQLite-backed hourly buckets
per entity_type (so memory survives restarts); likelihood is a circular
Gaussian KDE over the hour-of-day marginal, normalised to [0, 1] by the peak
hour. Builds on the entity_type taxonomy (ADR 0016).

Constraints honoured: persists across restarts (SQLite), Python 3.9, and stdlib
only — no pandas / scipy / numpy (the KDE is a few lines of ``math``). A small
TTL + LRU cache keeps hot queries well under the 100ms Jetson budget; it's
cleared on every record so a query never returns stale history.
"""

from __future__ import annotations

import math
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional, Tuple

from orpheus_common.detection.database import open_connection
from orpheus_common.logging import get_logger
from orpheus_common.storage import get_data_root

logger = get_logger(__name__)

# Bandwidth (in hours) for the circular hour-of-day KDE. σ=2 gives a smooth
# peak across an active window while driving far-off hours toward ~0 (verified
# against the acceptance thresholds: in-window >0.7, ~10h away <0.1).
_HOUR_KDE_SIGMA = 2.0
_HOURS = 24
_DEFAULT_CACHE_SIZE = 256
_DEFAULT_CACHE_TTL_SECONDS = 300.0


@dataclass(frozen=True)
class TimeWindow:
    """Optional temporal filters for a likelihood query. ``hour_of_day`` is the
    primary axis (0-23); ``day_of_week`` (0=Mon) and ``month`` (1-12) further
    restrict the history the marginal is built from."""

    hour_of_day: Optional[int] = None
    day_of_week: Optional[int] = None
    month: Optional[int] = None


@dataclass(frozen=True)
class TemporalPattern:
    """Marginal distributions of an entity_type's history."""

    entity_type: str
    hourly: List[int]   # 24 counts, index = hour_of_day
    daily: List[int]    # 7 counts, index = day_of_week (0=Mon)
    monthly: List[int]  # 12 counts, index = month - 1
    total: int


class StateSpaceMemory:
    """Persisted temporal memory of entity occurrences + likelihood queries.

    Not thread-safe: drive one instance from a single thread (the correlator
    uses it from its event-loop thread). Each operation opens and closes its own
    SQLite connection, so nothing is held across calls."""

    def __init__(
        self,
        db_path: Optional[Path] = None,
        *,
        cache_size: int = _DEFAULT_CACHE_SIZE,
        cache_ttl_seconds: float = _DEFAULT_CACHE_TTL_SECONDS,
    ) -> None:
        self._db_path = Path(db_path) if db_path else (get_data_root() / "state_space.db")
        # get_data_root() only resolves the dir, it doesn't create it; mirror
        # DetectionDB so a fresh deploy doesn't crash on the first connect.
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache_size = cache_size
        self._cache_ttl = cache_ttl_seconds
        self._cache: OrderedDict[tuple, Tuple[float, float]] = OrderedDict()
        self._ensure_schema()

    @classmethod
    def from_config(cls, config: Any, *, db_path: Optional[Path] = None) -> StateSpaceMemory:
        # Reserved for future tunables on config.correlation; the contract is
        # stable today, so this just centralises construction.
        return cls(db_path=db_path)

    def _ensure_schema(self) -> None:
        conn = open_connection(self._db_path)
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS state_space_buckets ("
                "entity_type TEXT NOT NULL, hour_of_day INTEGER NOT NULL, "
                "day_of_week INTEGER NOT NULL, month INTEGER NOT NULL, "
                "count INTEGER NOT NULL DEFAULT 0, "
                "PRIMARY KEY (entity_type, hour_of_day, day_of_week, month))"
            )
            conn.commit()
        finally:
            conn.close()

    def record_event(self, event: Any, *, now: Optional[datetime] = None) -> None:
        """Record one EntityEvent (model or emit-dict) into the hourly buckets.

        No-op when the event has no ``entity_type`` (unresolved entities carry no
        learnable signal). A genuinely-absent timestamp falls back to ``now``; a
        *present-but-unparseable* one is skipped — stamping it with wall-clock
        would silently corrupt the temporal marginal. Each call increments the
        bucket (it's a count, not a set)."""
        entity_type, raw_ts = _extract(event)
        if not entity_type:
            return
        if raw_ts is None:
            ts = _utc(now)
        else:
            parsed = _parse_ts(raw_ts)
            if parsed is None:
                logger.warning(
                    "Skipping state-space record: unparseable timestamp",
                    entity_type=entity_type,
                    timestamp=raw_ts,
                )
                return
            ts = _utc(parsed)
        conn = open_connection(self._db_path)
        try:
            conn.execute(
                "INSERT INTO state_space_buckets "
                "(entity_type, hour_of_day, day_of_week, month, count) VALUES (?, ?, ?, ?, 1) "
                "ON CONFLICT(entity_type, hour_of_day, day_of_week, month) "
                "DO UPDATE SET count = count + 1",
                (entity_type, ts.hour, ts.weekday(), ts.month),
            )
            conn.commit()
        finally:
            conn.close()
        self._invalidate_cache(entity_type)  # only this entity's history changed

    def query_likelihood(
        self, entity_type: str, time_window: TimeWindow, *, now: Optional[datetime] = None
    ) -> float:
        """Likelihood in [0, 1] of ``entity_type`` at ``time_window.hour_of_day``,
        normalised by the entity's peak hour. 0.0 if no history or no hour given."""
        if time_window.hour_of_day is None:
            return 0.0
        key = (entity_type, time_window.hour_of_day, time_window.day_of_week, time_window.month)
        cached = self._cache_get(key, now)
        if cached is not None:
            return cached
        hourly = self._hourly_marginal(entity_type, time_window)
        result = _kde_likelihood(hourly, time_window.hour_of_day)
        self._cache_put(key, result, now)
        return result

    def query_pattern(self, entity_type: str) -> TemporalPattern:
        """The full hourly/daily/monthly marginals for ``entity_type``."""
        hourly = [0] * _HOURS
        daily = [0] * 7
        monthly = [0] * 12
        conn = open_connection(self._db_path)
        try:
            cur = conn.execute(
                "SELECT hour_of_day, day_of_week, month, count FROM state_space_buckets "
                "WHERE entity_type = ?",
                (entity_type,),
            )
            for hour, dow, month, count in cur.fetchall():
                hourly[hour] += count
                daily[dow] += count
                monthly[month - 1] += count
        finally:
            conn.close()
        return TemporalPattern(
            entity_type=entity_type,
            hourly=hourly,
            daily=daily,
            monthly=monthly,
            total=sum(hourly),
        )

    def _hourly_marginal(self, entity_type: str, time_window: TimeWindow) -> List[int]:
        """24 hourly counts for ``entity_type``, restricted by any day_of_week /
        month filters set on the window."""
        clause = "WHERE entity_type = ?"
        params: List[Any] = [entity_type]
        if time_window.day_of_week is not None:
            clause += " AND day_of_week = ?"
            params.append(time_window.day_of_week)
        if time_window.month is not None:
            clause += " AND month = ?"
            params.append(time_window.month)
        hourly = [0] * _HOURS
        conn = open_connection(self._db_path)
        try:
            cur = conn.execute(
                f"SELECT hour_of_day, SUM(count) FROM state_space_buckets {clause} "
                "GROUP BY hour_of_day",
                params,
            )
            for hour, total in cur.fetchall():
                hourly[hour] = int(total or 0)
        finally:
            conn.close()
        return hourly

    # --- cache (TTL + size-bounded LRU; cleared on every record) ------------ #

    def _invalidate_cache(self, entity_type: str) -> None:
        """Drop cached likelihoods for one entity_type whose history just changed.
        Scoped so a busy entity doesn't evict every other entity's hot entries."""
        for key in [k for k in self._cache if k[0] == entity_type]:
            del self._cache[key]

    def _cache_get(self, key: tuple, now: Optional[datetime]) -> Optional[float]:
        entry = self._cache.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if _epoch(now) >= expires_at:
            del self._cache[key]
            return None
        self._cache.move_to_end(key)
        return value

    def _cache_put(self, key: tuple, value: float, now: Optional[datetime]) -> None:
        self._cache[key] = (value, _epoch(now) + self._cache_ttl)
        self._cache.move_to_end(key)
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)


def _kde_likelihood(hourly: List[int], hour: int) -> float:
    """Circular Gaussian KDE over the 24 hourly counts, evaluated at ``hour`` and
    normalised by the peak hour. Returns 0.0 when there's no history."""
    if sum(hourly) == 0:
        return 0.0

    def density(at: int) -> float:
        return sum(
            hourly[b] * _circular_gaussian(at, b, _HOURS, _HOUR_KDE_SIGMA)
            for b in range(_HOURS)
        )

    peak = max(density(h) for h in range(_HOURS))
    if peak <= 0.0:
        return 0.0
    return density(hour) / peak


def _circular_gaussian(a: int, b: int, period: int, sigma: float) -> float:
    raw = abs(a - b) % period
    dist = min(raw, period - raw)  # wrap-around distance
    return math.exp(-(dist * dist) / (2.0 * sigma * sigma))


def _extract(event: Any) -> Tuple[Optional[str], Any]:
    """(entity_type, raw_timestamp) from an EntityEvent model or an emit-dict.

    The timestamp is returned RAW (unparsed) so the caller can tell a genuinely
    absent timestamp from a present-but-malformed one."""
    if isinstance(event, dict):
        return event.get("entity_type"), event.get("timestamp")
    return getattr(event, "entity_type", None), getattr(event, "timestamp", None)


def _parse_ts(value: Any) -> Optional[datetime]:
    if value is None or isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _utc(dt: Optional[datetime]) -> datetime:
    if dt is None:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _epoch(now: Optional[datetime]) -> float:
    return _utc(now).timestamp()
