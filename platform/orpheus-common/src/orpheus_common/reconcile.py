"""``orpheus-reconcile`` — event-sourcing shadow reconciliation (the determinism
contract §3.3). Compares the durable domain stream against the SQLite DB by
``event_id`` set-difference for one agent-owned, 1:1-persisted detection type
(default ``audio.motion``).

Interpretation (shadow phase): **DB-only is EXPECTED** (the DB is the authoritative
writer; the stream is catching up / disabled on some hosts). **STREAM-only is the bug
worth catching** — a publish the DB never recorded, the integrity violation that would
corrupt a future rebuild. Derived ``entities`` are excluded (no 1:1 correspondence).
nats-only; a clean run (no stream-only ids) is the evidence a future "stream is truth"
flip is gated on.
"""

from __future__ import annotations

import argparse
from typing import Any, Optional, Set

from orpheus_common.logging import get_logger

logger = get_logger(__name__)

_DEFAULT_TYPE = "audio.motion"


def reconcile_event_ids(stream_ids: Set[str], db_ids: Set[str]) -> dict:
    """Pure set-difference reconciliation. ``equivalent`` is True iff every stream
    message has a matching DB row (no stream-only ids) — DB-only ids are expected
    during the shadow phase and do NOT count as divergence."""
    db_only = db_ids - stream_ids
    stream_only = stream_ids - db_ids
    return {
        "stream_count": len(stream_ids),
        "db_count": len(db_ids),
        "both": len(stream_ids & db_ids),
        "db_only": sorted(db_only),  # expected during shadow (DB is the writer)
        "stream_only": sorted(stream_only),  # the integrity violation to catch
        "equivalent": not stream_only,
    }


def collect_stream_event_ids(bus: Any, stream_name: str, detection_type: str) -> Set[str]:
    """Replay the durable stream and collect the ``event_id`` of every message of
    ``detection_type`` (entities + other types are ignored)."""
    ids: Set[str] = set()

    def _cb(_topic: str, payload: Any) -> None:
        if isinstance(payload, dict) and payload.get("detection_type") == detection_type:
            event_id = payload.get("event_id")
            if event_id:
                ids.add(str(event_id))

    bus.stream_replay(stream_name, _cb)
    return ids


def collect_db_event_ids(db: Any, detection_type: str) -> Set[str]:
    """The DB's ``event_id`` set for ``detection_type``.

    Streams via ``iter_query`` (holding only one batch in memory) rather than
    ``query(limit=1_000_000)`` — reconciliation must cover the WHOLE table, and
    materialising a full Jetson-scale detection window as ``Detection`` models at once
    is the OOM anti-pattern ``iter_query`` exists to kill. The set is order-independent,
    so the result is identical."""
    return {
        d.event_id
        for d in db.iter_query(detection_type=detection_type)
        if d.event_id
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="orpheus-reconcile",
        description="Reconcile the durable domain stream against the SQLite DB by "
        "event_id (event-sourcing shadow; determinism contract §3.3).",
    )
    parser.add_argument(
        "--detection-type", default=_DEFAULT_TYPE, help="1:1-persisted type to reconcile"
    )
    parser.add_argument(
        "--stream", default=None, help="stream name (default: event_sourcing.stream_name)"
    )
    args = parser.parse_args(argv)

    from orpheus_common.config import OrpheusConfig
    from orpheus_common.detection import DetectionDB
    from orpheus_common.event_bus import create_event_bus

    cfg = OrpheusConfig.get_instance()
    stream_name = args.stream or cfg.event_sourcing.stream_name

    bus = create_event_bus(cfg, client_id="orpheus-reconcile")
    bus.connect()
    try:
        stream_ids = collect_stream_event_ids(bus, stream_name, args.detection_type)
    finally:
        bus.disconnect()
    db_ids = collect_db_event_ids(DetectionDB(), args.detection_type)

    r = reconcile_event_ids(stream_ids, db_ids)
    print(
        f"detection_type={args.detection_type} stream={r['stream_count']} "
        f"db={r['db_count']} both={r['both']}"
    )
    print(f"db_only (expected during shadow): {len(r['db_only'])}")
    print(f"stream_only (INTEGRITY VIOLATION): {len(r['stream_only'])}")
    for event_id in r["stream_only"][:20]:
        print(f"  stream-only event_id: {event_id}")
    print("RECONCILED OK" if r["equivalent"] else "DIVERGENCE: stream messages with no DB row")
    return 0 if r["equivalent"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
