"""Historical event replay (Epic 4 — Event Bus Evolution).

Reads persisted Detections from a SQLite database and re-publishes them onto an
``EventBus`` with original-time spacing (optionally time-dilated), so a week of
real events can be streamed through a new agent for offline analysis,
regression testing, or counterfactual ("what would the Director have done?")
runs.

Built on the ``EventBus`` abstraction (see ADR 0015), so it works with the MQTT
backend today and any durable backend that registers later — no call-site
change. Every replayed payload is tagged so consumers (and humans) can never
mistake it for live data:

    {"_replay": true, "_replay_tag": "<label>", "_original_timestamp": "<iso>"}

CLI: ``orpheus-replay --source <db> [--speed N] [--start ISO] [--end ISO] [--tag L]``.
"""

from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, NamedTuple, Optional

from .detection.database import DetectionDB
from .detection.models import Detection
from .event_bus import EventBus, create_event_bus
from .logging import get_logger

logger = get_logger(__name__)

# detection_type → the topic the live agent publishes it on. Mirrors the
# correlator's ``correlation.input_topics`` (+ audio.motion) in orpheus.yaml,
# so replayed detections land where live consumers already listen. Unknown
# types fall back to REPLAY_FALLBACK_TOPIC; callers can override entirely with
# ``topic_for=``.
DETECTION_TYPE_TOPICS: dict[str, str] = {
    "species.detected": "orpheus/detection/bird/events",
    "crow.analyzed": "orpheus/detection/crow/events",
    "audio.classified": "orpheus/detection/audio/events",
    "audio.motion": "orpheus/audio/motion/events",
}
REPLAY_FALLBACK_TOPIC = "orpheus/detection/replay"
# Correlated EntityEvents all publish on one topic (the correlator's output).
ENTITIES_TOPIC = "orpheus/entities/animal"

VALID_KINDS = ("detections", "entities", "both")

# Row cap for the entity load (entities have no streaming iterator yet). Loud
# when hit — a silently truncated replay set is worse than a big one.
_ENTITY_LOAD_LIMIT = 1_000_000


class _ReplayEvent(NamedTuple):
    """A normalized replayable event: when it happened, where it goes, what it is."""

    timestamp: datetime
    topic: str
    payload: dict[str, Any]


def _ensure_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


class ReplayEngine:
    """Loads detections from a DB and replays them through an EventBus.

    ``sleep`` is injectable so tests can run instantly and assert the dilation
    schedule without real waits.
    """

    def __init__(
        self,
        bus: EventBus,
        *,
        tag: str = "replay",
        topic_for: Optional[Callable[[Detection], str]] = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._bus = bus
        self._tag = tag
        self._topic_for = topic_for or self._default_topic_for
        self._sleep = sleep
        self._events: list[_ReplayEvent] = []

    @staticmethod
    def _default_topic_for(detection: Detection) -> str:
        return DETECTION_TYPE_TOPICS.get(detection.detection_type, REPLAY_FALLBACK_TOPIC)

    def load(
        self,
        source: str,
        *,
        kind: str = "detections",
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> int:
        """Load events from the SQLite ``source``, sorted oldest-first.

        ``kind`` selects what to replay: ``"detections"`` (classifier outputs,
        each routed by its detection_type), ``"entities"`` (correlated
        EntityEvents on ``orpheus/entities/animal``), or ``"both"`` (merged in
        time order). Optional ``start``/``end`` bound the range (inclusive).
        Returns the number of events loaded.
        """
        if kind not in VALID_KINDS:
            raise ValueError(f"kind must be one of {VALID_KINDS}; got {kind!r}")
        db = DetectionDB(db_path=Path(source))
        events: list[_ReplayEvent] = []
        if kind in ("detections", "both"):
            # Stream via iter_query — no silent cap, and never an all-at-once
            # list of Detection models (materialising a whole window OOMs at
            # production scale; see iter_query's contract). The payload
            # dicts still materialise below because replay needs ascending time
            # order and iter_query streams newest-first — a fully-lazy merge
            # needs an ascending option on DetectionDB.iter_query (seam left
            # for the detection-DB owner).
            for det in db.iter_query(start_time=start, end_time=end):
                events.append(
                    _ReplayEvent(_ensure_utc(det.timestamp), self._topic_for(det), det.to_dict())
                )
        if kind in ("entities", "both"):
            entities = db.get_entities(
                start_time=start, end_time=end, limit=_ENTITY_LOAD_LIMIT
            )
            if len(entities) >= _ENTITY_LOAD_LIMIT:
                logger.warning(
                    "Entity load hit its row cap — the replay set is TRUNCATED "
                    "to the newest entities",
                    limit=_ENTITY_LOAD_LIMIT,
                )
            for ent in entities:
                events.append(
                    _ReplayEvent(_ensure_utc(ent.timestamp), ENTITIES_TOPIC, ent.to_dict())
                )
        # Chronological order so inter-event spacing is meaningful (esp. "both").
        self._events = sorted(events, key=lambda e: e.timestamp)
        logger.info(
            "Loaded events for replay",
            source=str(source),
            kind=kind,
            count=len(self._events),
            start=start.isoformat() if start else None,
            end=end.isoformat() if end else None,
        )
        return len(self._events)

    def play(self, speed: float = 1.0) -> int:
        """Replay the loaded events, preserving inter-event spacing / ``speed``.

        ``speed`` 1.0 = real-time, 10.0 = 10× faster, <= 0 = as fast as possible
        (no waiting). Each event keeps its ORIGINAL timestamp in the payload and
        is tagged ``_replay``. Returns the number of events published.
        """
        prev: Optional[datetime] = None
        published = 0
        for event in self._events:
            if prev is not None and speed and speed > 0:
                delay = (event.timestamp - prev).total_seconds() / speed
                if delay > 0:
                    self._sleep(delay)
            self._bus.publish(event.topic, self._replay_payload(event))
            prev = event.timestamp
            published += 1
        logger.info("Replay complete", published=published, tag=self._tag, speed=speed)
        return published

    def _replay_payload(self, event: _ReplayEvent) -> dict[str, Any]:
        payload = dict(event.payload)
        # Clearly mark as replay so no consumer mistakes it for live data.
        payload["_replay"] = True
        payload["_replay_tag"] = self._tag
        payload["_original_timestamp"] = event.timestamp.isoformat()
        return payload


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    return _ensure_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="orpheus-replay",
        description="Replay historical detections/entities from a SQLite DB onto the event bus.",
    )
    parser.add_argument("--source", required=True, help="Path to the detections SQLite DB.")
    parser.add_argument(
        "--kind",
        choices=VALID_KINDS,
        default="detections",
        help="What to replay: detections, entities, or both (default: detections).",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="Time-dilation: 1.0 real-time, 10.0 for 10x, 0 for as-fast-as-possible.",
    )
    parser.add_argument("--start", help="ISO start time (inclusive).")
    parser.add_argument("--end", help="ISO end time (inclusive).")
    parser.add_argument("--tag", default="replay", help="Label stamped into _replay_tag.")
    args = parser.parse_args(argv)

    # Lazy import to keep module import cheap and avoid loading config at import.
    from .config import OrpheusConfig

    config = OrpheusConfig.get_instance()
    bus = create_event_bus(config, client_id=f"orpheus-replay-{args.tag}")
    bus.connect()
    try:
        engine = ReplayEngine(bus, tag=args.tag)
        loaded = engine.load(
            args.source, kind=args.kind, start=_parse_iso(args.start), end=_parse_iso(args.end)
        )
        if loaded == 0:
            logger.warning("No events matched; nothing to replay.", source=args.source)
            return 0
        engine.play(speed=args.speed)
    finally:
        bus.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
