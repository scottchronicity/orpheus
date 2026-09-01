"""Hardware circuit breakers — hard rate limits at the actuation boundary.

A fuse-box for the physical world ([SAFETY] backlog item): if the Director agent
gets stuck in a positive feedback loop it must not play crow calls all night or
burn out a relay. The breaker enforces per-action limits ("max 3 audio playbacks
per hour") that higher-level agents cannot override.

This module is the reusable orpheus-common utility + its state machine. Wiring it
into the MCP middleware hook (intercept tool calls → ``check()`` before
forwarding) and the feeder-relay agent lands when the MCP actuation layer exists
(backlog ``[HARDWARE] Implement MCP Server`` — there is no MCP server yet, so
that integration is the remaining seam).

State is SQLite-backed with a sliding window so limits survive agent restarts
(an in-memory counter would reset on every crash — the opposite of a safety
guarantee). The MQTT trip notification is injected via ``on_trip`` so this stays
transport-agnostic and unit-testable; callers wire it to publish on
``orpheus/system/safety``.

Concurrency: separate ``check()`` + ``record()`` calls are NOT atomic — N callers
can all pass ``check()`` before any ``record()`` commits, admitting up to N
actions past the limit (bounded by concurrent in-flight callers, not one). Use
``record_if_allowed()`` for a race-free gate: it counts and inserts under a single
``BEGIN IMMEDIATE`` write transaction, so concurrent callers serialise and the
limit holds exactly. ``check()`` / ``record()`` remain for the MCP-style "check,
act, then record on success" flow, where the actuation layer serialises tool
calls per action. Neither path ever under-counts (blocks a legitimate action);
the only relaxation is the over-count above.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from orpheus_common.detection.database import open_connection
from orpheus_common.logging import get_logger
from orpheus_common.storage import get_data_root

logger = get_logger(__name__)


@dataclass(frozen=True)
class BreakerStatus:
    """Snapshot of one action's breaker (the contract in the backlog ASR)."""

    action: str
    count: int
    limit: int
    window_seconds: int
    is_tripped: bool
    resets_at: Optional[str]  # ISO-8601 when the oldest in-window event expires; None if count == 0


class CircuitBreaker:
    """Per-action sliding-window rate limiter backed by SQLite.

    ``limits`` maps an action name to ``(limit, window_seconds)``. An action with
    no configured limit is never throttled — ``check()`` returns True — so the
    fuse-box is opt-in per action.
    """

    def __init__(
        self,
        limits: dict[str, tuple[int, int]],
        *,
        db_path: Optional[Path] = None,
        on_trip: Optional[Callable[[BreakerStatus], None]] = None,
        default_limit: Optional[tuple[int, int]] = None,
    ) -> None:
        self._limits = dict(limits)
        # Optional fallback ``(limit, window_seconds)`` applied to any action NOT
        # in ``limits``. None (the default) preserves the historical behavior —
        # unconfigured actions are never throttled. Set it for dynamic action
        # keys sharing one policy (e.g. per-client API rate limiting, portal
        # prerequisite N2, where the action is the client id).
        self._default_limit = default_limit
        self._db_path = Path(db_path) if db_path else (get_data_root() / "circuit_breakers.db")
        self._on_trip = on_trip
        # In-memory set of actions currently believed tripped, so on_trip fires
        # once on the allowed→denied edge rather than on every denied check
        # (a runaway agent hammering check() would otherwise storm the topic).
        # Best-effort only — a restart re-notifies once on the next denial,
        # which is the desirable "still tripped after restart" signal anyway.
        self._tripped: set[str] = set()
        # Records since the last cross-action sweep (see _global_sweep). The
        # per-record prune is per-ACTION only, so one-off action keys (dynamic
        # per-client rate limiting: rotated JWTs, attacker-chosen tokens) each
        # leave immortal rows behind; the periodic global sweep bounds that.
        self._records_since_sweep = 0
        self._ensure_schema()

    @classmethod
    def from_config(
        cls,
        config: Any,
        *,
        db_path: Optional[Path] = None,
        on_trip: Optional[Callable[[BreakerStatus], None]] = None,
    ) -> CircuitBreaker:
        """Build from an ``OrpheusConfig`` (reads ``config.circuit_breakers``)."""
        limits = {
            action: (lim.limit, lim.window_seconds)
            for action, lim in config.circuit_breakers.items()
        }
        return cls(limits, db_path=db_path, on_trip=on_trip)

    # Records between cross-action sweeps. Class attribute so a test (or an
    # unusual caller) can tune it per instance; 1000 keeps the sweep ~free
    # relative to the per-record write it piggybacks on.
    _sweep_every = 1000

    def _ensure_schema(self) -> None:
        conn = open_connection(self._db_path)
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS circuit_breaker_events ("
                "action TEXT NOT NULL, occurred_at TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_cb_action_time "
                "ON circuit_breaker_events(action, occurred_at)"
            )
            conn.commit()
        finally:
            conn.close()

    def _max_window_seconds(self) -> Optional[int]:
        """The largest configured window — the horizon past which EVERY row is
        dead weight regardless of its action key. None when nothing is gated."""
        windows = [window for (_, window) in self._limits.values()]
        if self._default_limit is not None:
            windows.append(self._default_limit[1])
        return max(windows) if windows else None

    def _global_sweep(self, conn: Any, now: datetime) -> None:
        """Delete rows older than every configured window across ALL actions.

        The per-record prune only touches the SAME action key, so a ledger keyed
        by dynamic client ids (per-client API rate limiting) accretes one immortal
        row-set per never-seen-again key — a slow unauthenticated disk-fill on a
        public host. Uses the LARGEST window so no live action's in-window rows
        are ever touched. Runs every ``_sweep_every`` records off the record
        call's own ``now`` (never the wall clock — the injectable-now contract
        must hold for the sweep too); the caller owns the commit."""
        window = self._max_window_seconds()
        if window is None:
            return
        cutoff = (now - timedelta(seconds=window)).isoformat()
        conn.execute("DELETE FROM circuit_breaker_events WHERE occurred_at < ?", (cutoff,))

    def _maybe_global_sweep(self, conn: Any, now: datetime) -> None:
        """Piggyback the global sweep onto every Nth record (caller commits)."""
        self._records_since_sweep += 1
        if self._records_since_sweep >= self._sweep_every:
            self._records_since_sweep = 0
            self._global_sweep(conn, now)

    def _limit_for(self, action: str) -> Optional[tuple[int, int]]:
        """The ``(limit, window)`` gating ``action``: its configured entry, else
        the instance default (when set), else None (ungated)."""
        return self._limits.get(action, self._default_limit)

    def check(self, action: str, *, now: Optional[datetime] = None) -> bool:
        """Return True if ``action`` may proceed (count in window < limit).

        Unconfigured actions always pass. When a configured action is denied,
        the ``on_trip`` callback (if any) fires with the current status — wire it
        to publish the trip to ``orpheus/system/safety``.
        """
        limit_pair = self._limit_for(action)
        if limit_pair is None:
            return True
        now = _utc(now)
        limit, window = limit_pair
        count, _ = self._window_stats(action, window, now)
        allowed = count < limit
        self._notify(action, allowed, now)
        return allowed

    def record(self, action: str, *, now: Optional[datetime] = None) -> None:
        """Record one occurrence of ``action`` (call after a successful action).

        No-op for an unconfigured action: it isn't gated, so recording it would
        only grow the table with rows nothing ever reads.
        """
        limit_pair = self._limit_for(action)
        if limit_pair is None:
            return
        now = _utc(now)
        _, window = limit_pair
        conn = open_connection(self._db_path)
        try:
            conn.execute(
                "INSERT INTO circuit_breaker_events (action, occurred_at) VALUES (?, ?)",
                (action, now.isoformat()),
            )
            # Opportunistic prune: drop this action's now-expired events so the
            # table stays bounded over long runs.
            cutoff = (now - timedelta(seconds=window)).isoformat()
            conn.execute(
                "DELETE FROM circuit_breaker_events WHERE action = ? AND occurred_at < ?",
                (action, cutoff),
            )
            self._maybe_global_sweep(conn, now)
            conn.commit()
        finally:
            conn.close()

    def record_if_allowed(self, action: str, *, now: Optional[datetime] = None) -> bool:
        """Atomic gate: count + record under a single write transaction.

        Returns True (and records the occurrence) if within limit, or False
        (recording nothing) if the breaker is tripped. Unlike separate
        ``check()`` + ``record()`` this is race-free under concurrent callers —
        ``BEGIN IMMEDIATE`` serialises them so the limit holds exactly. This is
        the primitive an actuation gate should use. Unconfigured actions are
        always allowed and not recorded.
        """
        limit_pair = self._limit_for(action)
        if limit_pair is None:
            return True
        now = _utc(now)
        limit, window = limit_pair
        cutoff = (now - timedelta(seconds=window)).isoformat()
        conn = open_connection(self._db_path)
        # Autocommit off so we drive BEGIN IMMEDIATE / COMMIT explicitly: the
        # count-then-insert runs under one held write lock (concurrent callers
        # block on it via busy_timeout instead of racing the read).
        conn.isolation_level = None
        try:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute(
                "SELECT COUNT(*) FROM circuit_breaker_events "
                "WHERE action = ? AND occurred_at >= ?",
                (action, cutoff),
            )
            allowed = int(cur.fetchone()[0]) < limit
            if allowed:
                conn.execute(
                    "INSERT INTO circuit_breaker_events (action, occurred_at) VALUES (?, ?)",
                    (action, now.isoformat()),
                )
                conn.execute(
                    "DELETE FROM circuit_breaker_events WHERE action = ? AND occurred_at < ?",
                    (action, cutoff),
                )
                self._maybe_global_sweep(conn, now)
            conn.execute("COMMIT")
        finally:
            conn.close()
        self._notify(action, allowed, now)
        return allowed

    def reset(self, action: str) -> None:
        """Clear all recorded occurrences for ``action`` (manual breaker reset)."""
        conn = open_connection(self._db_path)
        try:
            conn.execute("DELETE FROM circuit_breaker_events WHERE action = ?", (action,))
            conn.commit()
        finally:
            conn.close()
        # Clear the notification latch too: after a manual reset the next
        # allowed→denied transition is a FRESH trip and must re-fire on_trip
        # (otherwise a reset breaker re-trips silently).
        self._tripped.discard(action)

    def get_status(self, action: str, *, now: Optional[datetime] = None) -> BreakerStatus:
        """Return the current :class:`BreakerStatus` for ``action``."""
        now = _utc(now)
        limit_pair = self._limit_for(action)
        if limit_pair is None:
            return BreakerStatus(action, 0, 0, 0, False, None)
        limit, window = limit_pair
        count, oldest = self._window_stats(action, window, now)
        resets_at = (
            (oldest + timedelta(seconds=window)).isoformat()
            if (count > 0 and oldest is not None)
            else None
        )
        return BreakerStatus(action, count, limit, window, count >= limit, resets_at)

    def _notify(self, action: str, allowed: bool, now: datetime) -> None:
        """Fire ``on_trip`` once on the allowed→denied edge (not on every denied
        call) and clear the latch on recovery, so a hammered breaker emits one
        notification per trip rather than a storm."""
        if self._on_trip is None:
            return
        if not allowed and action not in self._tripped:
            self._tripped.add(action)
            try:
                self._on_trip(self.get_status(action, now=now))
            except Exception:  # noqa: BLE001 - a trip notifier must never break the safety gate
                logger.exception("circuit breaker on_trip callback failed", action=action)
        elif allowed and action in self._tripped:
            self._tripped.discard(action)

    def _window_stats(
        self, action: str, window: int, now: datetime
    ) -> tuple[int, Optional[datetime]]:
        """``(count, oldest_event)`` for ``action`` within the trailing window.

        Timestamps are stored + compared as UTC-aware ISO-8601, so the
        lexicographic ``>=`` comparison is chronological.
        """
        cutoff = (now - timedelta(seconds=window)).isoformat()
        conn = open_connection(self._db_path)
        try:
            cur = conn.execute(
                "SELECT COUNT(*), MIN(occurred_at) FROM circuit_breaker_events "
                "WHERE action = ? AND occurred_at >= ?",
                (action, cutoff),
            )
            count, oldest = cur.fetchone()
            return int(count), (datetime.fromisoformat(oldest) if oldest else None)
        finally:
            conn.close()


def _utc(now: Optional[datetime]) -> datetime:
    """Normalise to UTC-aware (naive is treated as UTC), matching how timestamps
    are stored so the string comparison stays consistent."""
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)
