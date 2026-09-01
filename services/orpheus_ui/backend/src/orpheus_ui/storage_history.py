"""Daily storage-usage history + fill-rate projection.

"Free space right now" is nearly useless on a box that records
continuously — what you want is the *rate of change* and "how many days
until full". This module persists one usage sample per volume per day and
computes the slope.

Pieces:
  - ``StorageHistoryDB`` — a ``storage_history`` table keyed by
    ``(day, volume_key)`` so re-sampling the same day just updates the row
    (at most one point per volume per day, regardless of how often the
    sampler runs).
  - ``sample_now`` — read every registered volume (see
    ``orpheus_common.system.list_storage_volumes``) and upsert today's row.
  - ``compute_rate_and_projection`` — a pure function (least-squares slope
    over the daily series) returning signed free-bytes/day and projected
    days-until-full. Pure so the math is unit-tested without a DB.

The sampler runs as a background task in the always-on UI service (see
``main.lifespan``), so there's no extra systemd unit to manage. History is
forward-looking: it begins accumulating the day this deploys.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

from orpheus_common.detection import open_connection
from orpheus_common.logging import get_logger
from orpheus_common.storage import get_data_root
from orpheus_common.system import list_storage_volumes

logger = get_logger(__name__)

_instance: Optional[StorageHistoryDB] = None
_instance_lock = threading.Lock()


def get_storage_history_db() -> StorageHistoryDB:
    """The process-wide ``StorageHistoryDB``, constructed once on first use.

    ``__init__`` runs ``_init_schema`` (a ``CREATE TABLE IF NOT EXISTS`` + commit) —
    a WRITE against ``detections/orpheus.db``, the same physical file the correlator
    writes to. Constructing a fresh instance per Diagnostics request (polled ~60s)
    re-ran that write and took a lock on the shared live DB every time; caching runs
    the schema init once, the same contention fix ``db.get_detection_db`` applies for
    ``DetectionDB``. Double-checked locking so racing first requests build one
    instance. Construct ``StorageHistoryDB`` nowhere else."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = StorageHistoryDB()
    return _instance


def _default_db_path() -> Path:
    """Same SQLite file the detections/equivalence data lives in, so it
    backs up and moves together (one DB per deployment)."""
    detections_dir = get_data_root() / "detections"
    detections_dir.mkdir(parents=True, exist_ok=True)
    return detections_dir / "orpheus.db"


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


class StorageHistoryDB:
    """SQLite-backed daily storage-usage history."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else _default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _open(self) -> sqlite3.Connection:
        # Share the project-standard pragmas (WAL + busy_timeout=5000 +
        # synchronous=NORMAL) with every other writer on this file —
        # crucial because storage_history.db is the same physical file
        # as detections/equivalence (see ``_default_db_path``). Without
        # this, the storage sampler can be the FIRST writer on a fresh
        # box (it runs in the UI lifespan; DetectionDB is created lazily
        # on first API request) and would create the file in rollback-
        # journal mode — meaning every concurrent reader blocks during
        # the next sample. WAL flips happen once per file and persist.
        return open_connection(self.db_path)

    def _init_schema(self) -> None:
        conn = self._open()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS storage_history (
                    day         TEXT NOT NULL,
                    volume_key  TEXT NOT NULL,
                    label       TEXT NOT NULL,
                    path        TEXT NOT NULL,
                    total_bytes INTEGER,
                    used_bytes  INTEGER,
                    free_bytes  INTEGER,
                    sampled_at  TEXT NOT NULL,
                    PRIMARY KEY (day, volume_key)
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    def sample_now(self, day: Optional[str] = None) -> int:
        """Upsert today's usage row for every registered volume.

        Idempotent per day: re-running overwrites today's row with the
        latest reading. Returns the number of volumes sampled. Volumes that
        failed to read (``ok`` False) are skipped — we don't want to write
        NULL usage that would corrupt the slope.
        """
        day = day or _today()
        sampled_at = datetime.now(timezone.utc).isoformat()
        volumes = list_storage_volumes()
        written = 0
        conn = self._open()
        try:
            for vol in volumes:
                if not vol.get("ok") or vol.get("total") is None:
                    continue
                conn.execute(
                    """
                    INSERT INTO storage_history
                        (day, volume_key, label, path,
                         total_bytes, used_bytes, free_bytes, sampled_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (day, volume_key) DO UPDATE SET
                        label       = excluded.label,
                        path        = excluded.path,
                        total_bytes = excluded.total_bytes,
                        used_bytes  = excluded.used_bytes,
                        free_bytes  = excluded.free_bytes,
                        sampled_at  = excluded.sampled_at
                    """,
                    (
                        day,
                        vol["key"],
                        vol["label"],
                        vol["path"],
                        vol["total"],
                        vol["used"],
                        vol["free"],
                        sampled_at,
                    ),
                )
                written += 1
            conn.commit()
        finally:
            conn.close()
        return written

    def history(self, volume_key: str, days: int = 30) -> list[dict[str, Any]]:
        """Daily series for one volume, oldest → newest, last ``days`` days."""
        conn = self._open()
        try:
            cur = conn.execute(
                """
                SELECT day, total_bytes, used_bytes, free_bytes, sampled_at
                FROM storage_history
                WHERE volume_key = ?
                ORDER BY day DESC
                LIMIT ?
                """,
                (volume_key, days),
            )
            rows = cur.fetchall()
        finally:
            conn.close()
        rows.reverse()  # back to oldest → newest for charting
        return [
            {
                "day": r[0],
                "total_bytes": r[1],
                "used_bytes": r[2],
                "free_bytes": r[3],
                "sampled_at": r[4],
            }
            for r in rows
        ]


def compute_rate_and_projection(
    series: list[dict[str, Any]], current_free: Optional[int]
) -> dict[str, Optional[float]]:
    """Least-squares fill rate + days-until-full from a daily series.

    ``series`` is oldest → newest with ``day`` (ISO date) and ``free_bytes``.
    Returns:
        free_bytes_per_day: signed slope of free space (negative = filling).
            None if fewer than 2 distinct days.
        projected_days_until_full: ``current_free / fill_rate`` when free
            space is shrinking; None when it's flat/growing or no rate.
    """
    points: list[tuple[int, float]] = []
    first: Optional[date] = None
    for row in series:
        free = row.get("free_bytes")
        if free is None:
            continue
        d = date.fromisoformat(row["day"])
        if first is None:
            first = d
        points.append(((d - first).days, float(free)))

    # Need at least two points spanning different days for a slope.
    xs = {p[0] for p in points}
    if len(points) < 2 or len(xs) < 2:
        return {"free_bytes_per_day": None, "projected_days_until_full": None}

    n = len(points)
    sx = sum(p[0] for p in points)
    sy = sum(p[1] for p in points)
    sxx = sum(p[0] * p[0] for p in points)
    sxy = sum(p[0] * p[1] for p in points)
    denom = n * sxx - sx * sx
    if denom == 0:
        return {"free_bytes_per_day": None, "projected_days_until_full": None}
    slope = (n * sxy - sx * sy) / denom  # free bytes per day (signed)

    projected: Optional[float] = None
    if slope < 0 and current_free is not None:
        # Free space shrinking: days until it hits zero at this rate.
        projected = round(current_free / (-slope), 1)

    return {
        "free_bytes_per_day": round(slope, 2),
        "projected_days_until_full": projected,
    }
