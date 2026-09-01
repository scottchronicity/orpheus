"""One-shot backfill helpers for the cross-classifier-identity migration.

When the Layer 1.5 root_event_id column was added (see
``docs/designs/cross-classifier-identity.md`` §1.1), existing detection
rows landed with ``root_event_id = NULL``. They continue to work via
fallback paths (correlator falls back to source_event_id, chain queries
find no chain), but they don't participate in the Layer 3 auto-discovery
worker or appear in chain-walk results until the chain is populated.

This module's :func:`backfill_root_event_ids` walks the
``source_event_id`` chain via repeated DB lookups and writes the
discovered root back to each row. Run once per deployment after
upgrading.

Usage:
    from orpheus_common.detection import DetectionDB
    from orpheus_common.detection.backfill import backfill_root_event_ids

    db = DetectionDB()
    stats = backfill_root_event_ids(db)
    print(f"Backfilled {stats['updated']} of {stats['scanned']} rows")
"""

from __future__ import annotations

import sqlite3
from typing import Any, Optional

from .database import DetectionDB, open_connection

# Emit a progress line every this many rows scanned. The backfill runs over
# multi-million-row tables on the Jetson with no other feedback, so periodic
# progress is the difference between "working" and "looks hung".
_PROGRESS_EVERY = 100_000


def _find_root_event_id(
    conn: sqlite3.Connection,
    event_id: str,
    *,
    max_hops: int = 10,
) -> Optional[str]:
    """Walk the ``source_event_id`` chain back to its root.

    Returns the event_id of the audio.motion event at the chain root, or
    ``None`` if the chain breaks (a referenced source_event_id doesn't
    exist in the DB) or exceeds ``max_hops`` (cycle protection).

    "Root" is defined as: the first event in the chain whose
    detection_type is ``audio.motion`` OR whose ``source_event_id`` is
    NULL (no further upstream). Either is a valid chain end.
    """
    cursor = conn.cursor()
    current = event_id
    visited: set[str] = set()
    for _ in range(max_hops):
        if current in visited:
            return None  # cycle
        visited.add(current)

        cursor.execute(
            "SELECT detection_type, source_event_id, root_event_id "
            "FROM detections WHERE event_id = ?",
            (current,),
        )
        row = cursor.fetchone()
        if row is None:
            # The chain references a non-existent event_id — we lost the
            # root. Give up on this row.
            return None

        det_type, source_event_id, existing_root = row

        # If this event already knows its root (likely the audio.motion
        # itself, where root_event_id == event_id), use it.
        if existing_root:
            return existing_root

        # audio.motion is its own root by convention.
        if det_type == "audio.motion":
            return current

        # No further upstream → this is effectively the root.
        if not source_event_id:
            return current

        current = source_event_id

    return None  # exceeded max_hops


def backfill_root_event_ids(
    db: DetectionDB,
    *,
    batch_size: int = 1000,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Populate ``root_event_id`` on every detection row that lacks one.

    Walks the ``source_event_id`` chain to the audio.motion at the
    root and writes that event_id back to the row. Idempotent — runs
    after the first run are no-ops.

    Args:
        db: The DetectionDB to backfill.
        batch_size: How many UPDATE rows to commit per transaction.
        dry_run: If True, scan + compute but don't write back.

    Returns:
        ``{"scanned": int, "updated": int, "skipped_chain_broken": int,
            "skipped_cycle_or_deep": int}``

    Concurrency: opens a separate connection on the same file via
    ``open_connection``, so it inherits the project-standard WAL +
    ``synchronous=NORMAL`` pragmas (readers and the live agent writers
    proceed concurrently — WAL is already set on the file by DetectionDB).
    It overrides only ``busy_timeout`` to 30s so transient contention with
    those writers is retried rather than failing the backfill with
    SQLITE_BUSY. For a large backfill against a busy site, consider
    pausing the agents first.

    Memory: streams candidates in batches via ``LIMIT`` rather than
    loading the entire candidate list into memory. On a multi-million-row
    detections table this matters — the older all-in-memory implementation
    OOM'd on Jetson at production scale.
    """
    conn = open_connection(db.db_path)
    # Override open_connection's default 5s busy_timeout with 30s — long
    # enough to ride out contention with the live agents writing on the same
    # DB, short enough to abort if something is actually deadlocked.
    conn.execute("PRAGMA busy_timeout = 30000")
    try:
        cur = conn.cursor()

        # For dry_run, we want to count everything — load all candidate
        # event_ids once. Memory cost is one short string per nullable
        # row, accepted for the dry-run reporting use case.
        if dry_run:
            cur.execute(
                "SELECT event_id FROM detections WHERE root_event_id IS NULL"
            )
            candidates = [row[0] for row in cur.fetchall()]
            scanned = len(candidates)
            print(f"  scanning {scanned} candidate rows (dry-run)...", flush=True)
            updated = 0
            broken = 0
            for i, event_id in enumerate(candidates, 1):
                root = _find_root_event_id(conn, event_id)
                if root is None:
                    broken += 1
                else:
                    updated += 1
                if i % _PROGRESS_EVERY == 0:
                    print(
                        f"  ...{i}/{scanned} scanned  "
                        f"updated={updated}  broken={broken}",
                        flush=True,
                    )
            return {
                "scanned": scanned,
                "updated": updated,
                "skipped_chain_broken": broken,
                "skipped_cycle_or_deep": 0,
                "dry_run": True,
            }

        # Real run: stream batches by paging through `WHERE root_event_id
        # IS NULL` in rowid order. We maintain a `broken_offset` counter
        # so broken-chain rows (which stay NULL forever — their chain
        # references a non-existent event_id) get skipped past on the
        # next iteration instead of being re-fetched in an infinite
        # loop.
        #
        # Successfully-updated rows DON'T need to be skipped via offset:
        # their UPDATE moves them out of the WHERE-IS-NULL set, so the
        # next SELECT naturally returns the rows that come after them in
        # rowid order — without us touching the offset.
        #
        # Concurrent live writers always get strictly-higher rowids than
        # existing rows (SQLite auto-increment), so they appear AFTER
        # our offset on subsequent iterations — we don't lose them, we
        # just see them in a later pass.
        scanned = 0
        updated = 0
        broken = 0
        broken_offset = 0
        next_report = _PROGRESS_EVERY
        print("  starting backfill (live)...", flush=True)
        while True:
            cur.execute(
                "SELECT event_id FROM detections "
                "WHERE root_event_id IS NULL "
                "ORDER BY rowid "
                "LIMIT ? OFFSET ?",
                (batch_size, broken_offset),
            )
            batch = [row[0] for row in cur.fetchall()]
            if not batch:
                break

            pending_updates: list[tuple[str, str]] = []
            batch_broken = 0
            for event_id in batch:
                scanned += 1
                root = _find_root_event_id(conn, event_id)
                if root is None:
                    broken += 1
                    batch_broken += 1
                    continue
                pending_updates.append((root, event_id))

            # Advance past the broken rows in this batch — they stay
            # NULL forever, so a subsequent SELECT without an offset
            # bump would re-fetch them and loop.
            broken_offset += batch_broken

            if pending_updates:
                cur.executemany(
                    "UPDATE detections SET root_event_id = ? WHERE event_id = ?",
                    pending_updates,
                )
                conn.commit()
                updated += len(pending_updates)

            if scanned >= next_report:
                print(
                    f"  ...{scanned} scanned  updated={updated}  broken={broken}",
                    flush=True,
                )
                next_report += _PROGRESS_EVERY

        return {
            "scanned": scanned,
            "updated": updated,
            "skipped_chain_broken": broken,
            "skipped_cycle_or_deep": 0,
            "dry_run": False,
        }
    finally:
        conn.close()
