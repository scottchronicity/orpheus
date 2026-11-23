"""Corollary discharge — the "echo problem" filter.

When Orpheus plays a sound through the speaker, its own microphone hears it and
triggers a detection. This filter keeps a ring buffer of recent playback windows
(registered from ``orpheus/actuation/audio/playback`` events emitted by the
audio-playback agent) and TAGS entities whose time span overlaps a window as
``is_self_generated`` — so the correlator doesn't count the system hearing
itself as wildlife. It tags, never drops (per the [CORE] Corollary Discharge
ASR: keep self-generated events in the DB for future analysis).

This is a classic corollary-discharge problem from neuroscience: the system must
predict and cancel its own sensory consequences. Per the ASR, this filtering
lives in the event-correlator (NOT in the ML inference agents).

Timing: the playback agent publishes a start marker as soon as output begins and
a matching finish event with measured elapsed duration. This makes the interval
available before a long playback ends. An unclosed start is bounded by the
configured maximum playback duration, after which it is evicted. Playback
events only add a tag; detections and evidence are never discarded, including
real wildlife heard while a speaker is active.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from orpheus_common.logging import get_logger

logger = get_logger(__name__)

# The actuation topic the audio-playback agent publishes playback windows on.
PLAYBACK_TOPIC = "orpheus/actuation/audio/playback"

_DEFAULT_MAX_WINDOWS = 100
_DEFAULT_RETENTION_SECONDS = 300.0  # evict windows older than 5 minutes


@dataclass
class PlaybackWindow:
    """A playback window: [start, end], end includes buffer.

    Overlap means the detection is TAGGED is_self_generated — never
    dropped (the tags-not-drops contract at the top of this module).
    """

    start: datetime
    end: datetime
    source: str
    playback_id: str = ""
    provisional: bool = False


class CorollaryDischargeFilter:
    """Ring buffer of recent playback windows + overlap test for entities.

    ``buffer_seconds`` pads each window's tail (reverb / slightly-late
    detections). Windows auto-evict after ``retention_seconds`` and the buffer
    is capped at ``max_windows`` entries.
    """

    def __init__(
        self,
        buffer_seconds: float = 2.0,
        *,
        max_windows: int = _DEFAULT_MAX_WINDOWS,
        retention_seconds: float = _DEFAULT_RETENTION_SECONDS,
        max_open_seconds: float = _DEFAULT_RETENTION_SECONDS,
    ) -> None:
        self.buffer_seconds = buffer_seconds
        # A started-but-unfinished window must outlive its own maximum length,
        # or a playback longer than the retention stops being recognised as
        # Orpheus's own sound partway through.
        self._retention_seconds = max(retention_seconds, max_open_seconds + buffer_seconds)
        self._max_open_seconds = max_open_seconds
        self._windows: deque[PlaybackWindow] = deque(maxlen=max_windows)

    def register_playback(
        self,
        start_time: datetime,
        duration_seconds: float,
        source: str = "",
        *,
        now: datetime | None = None,
    ) -> None:
        """Record a playback window [start, start + duration + buffer]."""
        start = _utc(start_time)
        end = start + timedelta(seconds=max(0.0, duration_seconds) + self.buffer_seconds)
        self._windows.append(PlaybackWindow(start=start, end=end, source=source))
        self._evict(_utc(now) if now is not None else datetime.now(UTC))

    def register_from_event(self, payload: Any, *, now: datetime | None = None) -> bool:
        """Register a window from a raw playback-event payload. Returns True if
        registered, False (with a warning) on a malformed payload."""
        if not isinstance(payload, dict):
            logger.warning("Ignoring non-dict playback event")
            return False
        try:
            start_dt = _parse_ts(payload["start_time"])
            phase = str(payload.get("phase", "finished"))
            playback_id = str(payload.get("playback_id", ""))
            duration = float(payload.get("duration_seconds", 0.0) or 0.0)
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("Ignoring malformed playback event", error=str(exc))
            return False
        source = str(payload.get("source", ""))
        received_at = _utc(now) if now is not None else datetime.now(UTC)

        if phase == "started":
            # The existing retention horizon bounds orphaned starts if the
            # playback process exits before it can publish the matching finish.
            end = start_dt + timedelta(
                seconds=self._max_open_seconds + self.buffer_seconds
            )
            self._windows.append(
                PlaybackWindow(
                    start=start_dt,
                    end=end,
                    source=source,
                    playback_id=playback_id,
                    provisional=True,
                )
            )
        elif phase == "finished" and playback_id:
            matching = next(
                (
                    window
                    for window in reversed(self._windows)
                    if window.playback_id == playback_id
                ),
                None,
            )
            if matching is not None:
                matching.end = start_dt + timedelta(
                    seconds=max(0.0, duration) + self.buffer_seconds
                )
                matching.provisional = False
                matching.source = source
            else:
                # A consumer can restart between start and finish. The finish
                # still carries the complete measured interval.
                self.register_playback(start_dt, duration, source, now=received_at)
        elif phase in ("finished", "complete", "completed"):
            # Backwards-compatible payloads from playback agents predating the
            # start/finish protocol contain only one measured window.
            self.register_playback(start_dt, duration, source, now=received_at)
        else:
            logger.warning("Ignoring playback event with unknown phase", phase=phase)
            return False

        self._evict(received_at)
        return True

    def is_self_generated(
        self, entity_event: dict[str, Any], *, now: datetime | None = None
    ) -> bool:
        """True if the entity's time span overlaps any active playback window.

        The span comes from ``event_signature.start_time/end_time`` (the cluster's
        observation time range). Missing/unparseable span → False (can't claim
        self-generated without evidence)."""
        span = self._entity_span(entity_event)
        if span is None:
            return False
        start, end = span
        self._evict(_utc(now) if now is not None else datetime.now(UTC))
        # Interval overlap: [start, end] intersects [w.start, w.end].
        return any(w.start <= end and start <= w.end for w in self._windows)

    def _evict(self, now: datetime) -> None:
        cutoff = now - timedelta(seconds=self._retention_seconds)
        self._windows = deque(
            (
                window
                for window in self._windows
                if (window.start if window.provisional else window.end) >= cutoff
            ),
            maxlen=self._windows.maxlen,
        )

    @staticmethod
    def _entity_span(
        entity_event: dict[str, Any],
    ) -> tuple[datetime, datetime] | None:
        signature = entity_event.get("event_signature") or {}
        start_raw = signature.get("start_time")
        end_raw = signature.get("end_time")
        if not start_raw or not end_raw:
            return None
        try:
            return (_parse_ts(start_raw), _parse_ts(end_raw))
        except (TypeError, ValueError):
            return None


def _parse_ts(value: Any) -> datetime:
    """Parse an ISO-8601 string (or pass through a datetime) to UTC-aware."""
    if isinstance(value, datetime):
        return _utc(value)
    return _utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")))


def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)
