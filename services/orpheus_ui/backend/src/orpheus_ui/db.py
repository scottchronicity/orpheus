"""Process-wide cached ``DetectionDB`` accessor for the UI backend.

``DetectionDB.__init__`` runs ``_init_schema()`` + ``ensure_schema_updates()``
on every construction — multiple ``PRAGMA``s, ``CREATE TABLE IF NOT EXISTS`` and
~8 ``CREATE INDEX IF NOT EXISTS`` (a write/reserved lock on the file even when the
index already exists), plus a ``sqlite_master`` scan. The history endpoints poll
every 30s across several pages, so constructing a fresh ``DetectionDB`` per
request paid that migration cost on the hot path *and* momentarily contended with
the correlator's live writes — a direct contributor to the reported UI
sluggishness.

Each ``DetectionDB`` method opens its own short-lived connection through
``open_connection()`` and closes it in a ``finally``, so the instance itself
holds no live connection or per-request state. That makes a single shared
instance safe across FastAPI's sync threadpool: only the one-time ``__init__``
(schema migration) is shared; every query still gets its own connection.

``api/entities.py`` already proved this pattern with a module-local
``_get_db()``; this lifts it so ``api/diagnostics.py`` reuses the same cached
instance instead of re-instantiating per request.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Optional

from orpheus_common.detection import DetectionDB
from orpheus_common.logging import get_logger
from orpheus_common.storage import get_data_root

logger = get_logger(__name__)

_db: Optional[DetectionDB] = None
_lock = threading.Lock()


def resolve_replica_path() -> Path | None:
    """The mirror replica path when the UI should read from it, else ``None``.

    THE replica-routing predicate (``ui.read_from_replica`` + a configured
    ``mirror.staging_path`` + the file actually existing), shared by every
    UI reader (detections, weather) so they can never route differently.
    Falls back loudly: read_only handles cannot create a missing file, so a
    mis-timed flag flip must degrade to the live DB with a visible warning,
    not brick reads or (worse) silently serve the wrong database.
    """
    try:
        from orpheus_common.config import OrpheusConfig  # noqa: PLC0415

        cfg = OrpheusConfig.get_instance()
        ui = getattr(cfg, "ui", None)
        mirror = getattr(cfg, "mirror", None)
        replica = getattr(mirror, "staging_path", "") if mirror is not None else ""
        if ui is not None and getattr(ui, "read_from_replica", False) and replica:
            if Path(replica).exists():
                return Path(replica)
            logger.warning(
                "ui.read_from_replica is set but the replica snapshot is missing; "
                "falling back to the live DB",
                replica=replica,
            )
    except Exception as e:  # noqa: BLE001 - no/!loadable config -> live DB (the default)
        logger.warning(
            "Replica routing unavailable (config unreadable); "
            "falling back to the live DB",
            error=str(e),
        )
    return None


def _build_detection_db() -> DetectionDB:
    """Construct the shared ``DetectionDB``.

    When ``ui.read_from_replica`` is set AND a mirror replica path is configured
    (``mirror.staging_path``), read that replica **read-only** — the off-Jetson
    portal / contention relief (the UI never touches the live DB). Otherwise the
    live DB, exactly as before (the default). Config read is lazy so importing this
    module stays cheap.
    """
    query_timeout: float | None = None
    try:
        from orpheus_common.config import OrpheusConfig  # noqa: PLC0415

        cfg = OrpheusConfig.get_instance()
        ui = getattr(cfg, "ui", None)
        # Portal prerequisite N2: an optional per-query wall-time budget for the
        # UI's DB reads (0/absent = unbounded, today's behavior).
        timeout_val = getattr(ui, "query_timeout_seconds", 0.0) if ui is not None else 0.0
        if isinstance(timeout_val, (int, float)) and timeout_val > 0:
            query_timeout = float(timeout_val)
        replica = resolve_replica_path()
        if replica is not None:
            return DetectionDB(
                db_path=replica,
                read_only=True,
                statement_timeout_seconds=query_timeout,
            )
    except Exception as e:  # noqa: BLE001 - no/!loadable config -> live DB (today's default)
        # Absent/unloadable config is the normal default-deploy path, but a
        # failure HERE can also mean the replica handle was refused — either
        # way the fallback must be visible, not silent (an operator who set
        # the flag would otherwise believe the replica is serving).
        logger.warning(
            "Replica routing unavailable (config unreadable or replica handle "
            "failed); falling back to the live DB",
            error=str(e),
        )
    try:
        return DetectionDB(statement_timeout_seconds=query_timeout)
    except (OSError, sqlite3.OperationalError) as e:
        # Writer construction (mkdir + schema migration) can fail two ways
        # with very different right answers:
        #  - PERMANENT (unwritable data root — read-only portal host,
        #    mis-permissioned sandbox): degrade to a read-only handle so the
        #    GET endpoints keep serving.
        #  - TRANSIENT ("database is locked": another process is holding the
        #    writer lock, e.g. a minutes-long index build at fleet startup):
        #    degrading would cache a read-only, un-migrated handle for the
        #    process lifetime. Raise instead — the handle stays unset and the
        #    next request retries construction after the build commits.
        msg = str(e).lower()
        if "locked" in msg or "interrupted" in msg or "busy" in msg:
            logger.warning(
                "Live DB writer construction blocked by a concurrent writer "
                "(migration/index build?); will retry on the next request",
                error=str(e),
            )
            raise
        default_path = get_data_root() / "detections" / "orpheus.db"
        if default_path.exists():
            logger.warning(
                "Live DB is not writable; degrading to a read-only handle "
                "(no schema migration will run)",
                db_path=str(default_path),
                error=str(e),
            )
            return DetectionDB(
                db_path=default_path,
                read_only=True,
                statement_timeout_seconds=query_timeout,
            )
        raise


def get_detection_db() -> DetectionDB:
    """Return the process-wide ``DetectionDB``, constructing it once on first use.

    Double-checked locking so concurrent first requests (FastAPI runs sync
    endpoints in a threadpool) construct exactly one instance and run the schema
    migration once, not once-per-racing-request. The single construction point so
    every consumer honors the live-vs-read-only-replica choice (see
    ``_build_detection_db``); construct ``DetectionDB`` nowhere else.
    """
    global _db
    if _db is None:
        with _lock:
            if _db is None:
                _db = _build_detection_db()
    return _db
