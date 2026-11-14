"""SQLite database for storing detection events."""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

from orpheus_common.storage import get_data_root

from .models import Detection, Entity, EntityEvidence, TaxonomyRef, TemporalInterval


def _ensure_utc(dt: datetime) -> datetime:
    """Normalize a datetime to UTC.  Treats naive datetimes as UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso_lower_bound(dt: datetime) -> str:
    """Inclusive lower bound for SQLite string-comparison against the
    ``timestamp`` column. Normalizes to UTC + truncates microseconds so EVERY
    query path uses an identically-shaped bound (no drift — see the count_by_hour
    / species_distribution undercount bug this consolidates)."""
    return _ensure_utc(dt).replace(microsecond=0).isoformat()


def _iso_upper_bound(dt: datetime) -> str:
    """Inclusive upper bound (microsecond=999999 keeps the whole second in range)."""
    return _ensure_utc(dt).replace(microsecond=999999).isoformat()


# Public aliases: UI query paths build the same bounds so list vs stats can
# never query differently-shaped strings against the same UTC-stored column.
def iso_lower_bound(dt: datetime) -> str:
    return _iso_lower_bound(dt)


def iso_upper_bound(dt: datetime) -> str:
    return _iso_upper_bound(dt)




def _safe_model(cls: Any, data: dict[str, Any], *, context: str = "") -> Optional[Any]:
    """Construct a Pydantic model, returning ``None`` (with a warning) on a
    malformed row instead of aborting the whole read. Mirrors
    ``equivalence._safe_taxonomy_ref`` so a single bad persisted blob can't 500
    an entire query (e.g. one corrupt evidence object taking down /api/entities)."""
    try:
        return cls(**data)
    except Exception as exc:  # noqa: BLE001 - one bad row must not abort the read
        from orpheus_common.logging import get_logger  # noqa: PLC0415

        get_logger(__name__).warning(
            "Skipping malformed persisted row",
            model=cls.__name__,
            error=str(exc),
            context=context,
        )
        return None


def open_connection(
    db_path: Path,
    *,
    read_only: bool = False,
    statement_timeout_seconds: Optional[float] = None,
) -> sqlite3.Connection:
    """Open a SQLite connection with the project-standard pragmas.

    Applies (writer path, the default):
      - ``journal_mode = WAL`` — readers and a single writer can proceed
        concurrently. Crucial here: ~7 agents write detections + entities
        while the UI runs megaqueries; under the default rollback
        journal any writer takes an exclusive lock that blocks every
        concurrent reader, which is precisely the contention the user
        observed. WAL is on-disk and persists across opens, so this is
        a one-shot setting per DB file.
      - ``synchronous = NORMAL`` — safe under WAL (WAL preserves
        durability via its own checkpoint mechanism) and meaningfully
        reduces fsync cost per commit.
      - ``busy_timeout = 5000`` — when a connection does encounter a
        held lock, wait up to 5s instead of failing immediately with
        "database is locked". Matches the value already in use by
        ``TaxonomyEquivalenceDB``.

    With ``read_only=True`` the connection is opened via the SQLite URI
    ``mode=ro``: every write (INSERT/UPDATE/DDL, *and* the WAL/synchronous
    pragmas) raises ``sqlite3.OperationalError`` instead of mutating the file.
    This is the data-layer floor for read-only consumers that must not modify
    or migrate the DB — a read-only data mirror/replica and the LLM-facing
    observability surface that reads it. It is correct on the live DB and on a
    ``VACUUM INTO`` snapshot alike (no WAL pragma is issued, so no write is
    attempted). A static-replica ``immutable=1`` performance optimization can
    layer on later; it is deliberately omitted here because it is unsafe
    against a file still being written.

    All sqlite3 connections to this project's DBs should be opened
    through this helper so the pragmas apply uniformly (the inline
    sqlite3.connect calls in ``services/orpheus_ui/backend`` should
    use it too).
    """
    if read_only:
        # URI form so SQLite enforces read-only at the OS/driver level — any
        # write attempt raises rather than silently no-ops.
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        # busy_timeout is a connection runtime setting (not a write), so it is
        # safe on a read-only handle and lets a reader wait out a brief lock
        # rather than fail "database is locked".
        conn.execute("PRAGMA busy_timeout = 5000")
        _install_statement_timeout(conn, statement_timeout_seconds)
        return conn
    conn = sqlite3.connect(str(db_path))
    # journal_mode persists on the file but PRAGMA still must be set on
    # the connection that creates the file the first time. Cheap to
    # re-execute on subsequent opens — SQLite no-ops if already in WAL.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    _install_statement_timeout(conn, statement_timeout_seconds)
    return conn


def _install_statement_timeout(
    conn: sqlite3.Connection, timeout_seconds: Optional[float]
) -> None:
    """Bound this connection's query time via a progress-handler abort (portal
    prerequisite N2): once ``timeout_seconds`` of wall clock elapse, the handler
    returns non-zero and SQLite raises ``OperationalError: interrupted`` instead
    of letting a runaway query starve the box. None/<=0 installs nothing
    (today's behavior).

    Granularity is CONNECTION lifetime, which for this codebase's
    connection-per-query pattern (``DetectionDB._connect`` per call) equals
    per-query. Do NOT pass a timeout on long-lived streaming connections
    (``iter_query``) — the budget would span the whole stream."""
    if not timeout_seconds or timeout_seconds <= 0:
        return
    deadline = time.monotonic() + timeout_seconds

    def _abort_when_past_deadline() -> int:
        return 1 if time.monotonic() > deadline else 0

    # Check every N VM ops — coarse enough to be ~free, fine enough that an
    # expensive scan is interrupted within tens of milliseconds of the deadline.
    conn.set_progress_handler(_abort_when_past_deadline, 20_000)


def ensure_schema_updates(db_path: Path) -> None:
    """
    Safely migrate the database schema by adding new columns if missing.

    This runs on startup and uses ALTER TABLE to add columns that don't exist.
    SQLite ignores extra columns when reading with old code, making rollbacks safe.

    Args:
        db_path: Path to the SQLite database file.
    """
    conn = open_connection(db_path)
    try:
        # Index backfills below can hold the writer lock for minutes on a
        # large DB, and several agents run this migration concurrently at
        # startup. The default 5s busy_timeout would make every loser ERROR
        # out ("database is locked") and crash-loop instead of waiting for
        # the winner's build to commit — so this connection waits.
        conn.execute("PRAGMA busy_timeout = 600000")
        cursor = conn.cursor()
        # Check existing columns on detections.
        cursor.execute("PRAGMA table_info(detections)")
        existing_columns = {row[1] for row in cursor.fetchall()}

        if "event_metadata" not in existing_columns:
            cursor.execute("ALTER TABLE detections ADD COLUMN event_metadata TEXT")
        # ADR 0011 — intra-clip localisation and taxonomy reference.
        if "intervals_json" not in existing_columns:
            cursor.execute("ALTER TABLE detections ADD COLUMN intervals_json TEXT")
        if "taxonomy_namespace" not in existing_columns:
            cursor.execute("ALTER TABLE detections ADD COLUMN taxonomy_namespace TEXT")
        if "taxonomy_id" not in existing_columns:
            cursor.execute("ALTER TABLE detections ADD COLUMN taxonomy_id TEXT")
        # Cross-classifier-identity §1.1 — chain root (audio.motion event_id).
        if "root_event_id" not in existing_columns:
            cursor.execute("ALTER TABLE detections ADD COLUMN root_event_id TEXT")
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_root_event_id "
                "ON detections(root_event_id)"
            )

        # Backfill the compound indices on legacy DBs that initialised
        # before the new CREATE INDEX statements landed in _init_schema.
        # IF NOT EXISTS makes this safe and idempotent.
        #
        # CREATE INDEX on a large existing table (e.g. a year of
        # detections — tens of millions of rows) takes seconds-to-
        # minutes and holds the writer lock while running. WAL lets
        # concurrent readers proceed against the pre-build snapshot,
        # but writers (the correlator persisting incoming detections)
        # block until the build commits. Log a warning so a slow
        # first-run startup is attributable rather than a mystery.
        from orpheus_common.logging import get_logger  # noqa: PLC0415

        _log = get_logger(__name__)
        cursor.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='index' AND name IN "
            "('idx_detections_type_ts', 'idx_root_event_id_ts')"
        )
        existing = {row[0] for row in cursor.fetchall()}
        missing = {
            "idx_detections_type_ts",
            "idx_root_event_id_ts",
        } - existing
        if missing:
            # Only warn when the build is actually going to be slow: on a fresh
            # or small DB it is instant and a scary "this can take minutes"
            # line would be misleading. On a Jetson with a year of detections
            # this is the log line that explains a multi-minute first start.
            cursor.execute("SELECT count(*) FROM detections")
            detection_rows = cursor.fetchone()[0]
            if detection_rows > 50_000:
                _log.warning(
                    "Building compound index(es) on %d existing detection "
                    "rows — this holds the writer lock for seconds-to-minutes; "
                    "let it finish, it is not a hang",
                    detection_rows,
                    indices=sorted(missing),
                )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_detections_type_ts "
            "ON detections(detection_type, timestamp DESC)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_root_event_id_ts "
            "ON detections(root_event_id, timestamp)"
        )

        # Layer 2 — event_signature on entities table. Guarded by table
        # existence check so calling ensure_schema_updates() on a DB that
        # doesn't have the entities table yet (e.g. tests that init only
        # the detections table) is safe.
        cursor.execute("PRAGMA table_info(entities)")
        entity_cols = {row[1] for row in cursor.fetchall()}
        if entity_cols and "event_signature" not in entity_cols:
            cursor.execute("ALTER TABLE entities ADD COLUMN event_signature TEXT")
        # Corollary discharge — additive flag marking entities that overlapped
        # our own audio playback (the system hearing itself). Legacy rows get
        # DEFAULT 0 (False); the prior binary ignores the column.
        if entity_cols and "is_self_generated" not in entity_cols:
            cursor.execute(
                "ALTER TABLE entities ADD COLUMN is_self_generated INTEGER DEFAULT 0"
            )
        # Coarse entity_type taxonomy — additive nullable; legacy rows stay NULL
        # ([ARCH] Generalize the EntityEvent State Space Taxonomy).
        if entity_cols and "entity_type" not in entity_cols:
            cursor.execute("ALTER TABLE entities ADD COLUMN entity_type TEXT")

        # Backfill the Entities-page covering index on legacy DBs (same
        # pattern + rationale as the detections compound indices above:
        # IF NOT EXISTS is idempotent; the build holds the writer lock, so
        # warn when it will actually take time).
        if entity_cols:
            cursor.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='index' AND name = 'idx_entities_page_covering'"
            )
            if cursor.fetchone() is None:
                cursor.execute("SELECT count(*) FROM entities")
                entity_rows = cursor.fetchone()[0]
                if entity_rows > 50_000:
                    _log.warning(
                        "Building compound index(es) on %d existing entity "
                        "rows — this holds the writer lock for seconds-to-"
                        "minutes; let it finish, it is not a hang",
                        entity_rows,
                        indices=["idx_entities_page_covering"],
                    )
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_entities_page_covering "
                    "ON entities(timestamp, species, common_name, confidence)"
                )

        conn.commit()
    finally:
        conn.close()


class DetectionDB:
    """
    SQLite database for storing and querying detection events.

    Default location: /data/orpheus/detections/orpheus.db
    """

    def __init__(
        self,
        db_path: Optional[Path] = None,
        *,
        read_only: bool = False,
        statement_timeout_seconds: Optional[float] = None,
    ) -> None:
        """
        Initialize DetectionDB.

        Args:
            db_path: Path to SQLite database file. If None, uses default location.
            read_only: Open against a read-only replica/mirror. Skips schema init
                + migration (both writer operations) and opens every connection
                ``mode=ro``, so a read-only consumer — the off-Jetson dashboard,
                the public site — can never write or migrate the file (writes
                raise). The replica must already exist (the mirror produces it).
            statement_timeout_seconds: Optional per-query wall-time budget
                (portal prerequisite N2). Connections here are per-call, so the
                budget bounds each query; a query past it raises
                ``sqlite3.OperationalError: interrupted``. None/0 = unbounded
                (today's behavior). Intended for read-only portal consumers.
        """
        if db_path is None:
            detections_dir = get_data_root() / "detections"
            detections_dir.mkdir(parents=True, exist_ok=True)
            db_path = detections_dir / "orpheus.db"

        self.db_path = Path(db_path)
        self.read_only = read_only
        self.statement_timeout_seconds = statement_timeout_seconds
        # A read-only consumer never creates dirs, inits schema, or migrates —
        # those are writer operations. The replica is produced by the mirror.
        if not read_only:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._init_schema()
            ensure_schema_updates(self.db_path)

    def _connect(self) -> sqlite3.Connection:
        """Open a connection honoring this instance's ``read_only`` mode. Every
        query goes through here, so a read-only DetectionDB (e.g. against a
        replica) opens ``mode=ro`` and writes raise instead of mutating the file.
        ``statement_timeout_seconds`` (when set) bounds each query's wall time —
        connections are per-call here, so the budget is per-query."""
        return open_connection(
            self.db_path,
            read_only=self.read_only,
            statement_timeout_seconds=self.statement_timeout_seconds,
        )

    def _init_schema(self) -> None:
        """Initialize database schema.

        Waits out a concurrent migration rather than failing. Schema init and
        ``ensure_schema_updates`` race on every cold start: whichever process
        opens the database first can hold the write lock for minutes building
        indexes over a large history, and the default five-second timeout
        turns every other starter into a crash-and-restart. Observed on a
        station with 2.7M detections — an agent lost the race to the
        dashboard's index build and was restarted by systemd.
        """
        conn = self._connect()
        try:
            conn.execute("PRAGMA busy_timeout = 600000")
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS detections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT UNIQUE NOT NULL,
                    timestamp TEXT NOT NULL,
                    detection_type TEXT NOT NULL,
                    channel INTEGER,
                    species_code TEXT,
                    species_common TEXT,
                    confidence REAL,
                    audio_clip_path TEXT,
                    metadata TEXT,
                    source_event_id TEXT,
                    root_event_id TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    event_metadata TEXT
                )
            """)

            # Create indexes for common queries
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_timestamp
                ON detections(timestamp)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_detection_type
                ON detections(detection_type)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_species_code
                ON detections(species_code)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_channel
                ON detections(channel)
            """)
            # Compound index for the hot path: every Birds/Crows/
            # NOTE: the two compound indices idx_detections_type_ts and
            # idx_root_event_id_ts are intentionally NOT created here. They are
            # created in ensure_schema_updates() (which __init__ calls right
            # after this), for two reasons:
            #   1. Correctness — idx_root_event_id_ts references root_event_id,
            #      a column that on an UPGRADED old DB does not exist until
            #      ensure_schema_updates() ALTERs it in. Creating the index here
            #      (before the ALTER) raised "no such column: root_event_id" and
            #      crashed every process opening a pre-root_event_id database.
            #   2. Observability — ensure_schema_updates() logs a warning before
            #      building these on a large existing table (they hold the writer
            #      lock for seconds-to-minutes), so a slow first start after an
            #      upgrade is attributable instead of looking like a hang.

            # Entity table for correlated events. event_signature added in
            # Layer 2 (see cross-classifier-identity.md §4); legacy rows
            # have NULL via the additive migration in ensure_schema_updates.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS entities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_id TEXT UNIQUE NOT NULL,
                    timestamp TEXT NOT NULL,
                    species TEXT NOT NULL,
                    common_name TEXT,
                    confidence REAL,
                    evidence TEXT,
                    context TEXT,
                    event_signature TEXT,
                    is_self_generated INTEGER DEFAULT 0,
                    entity_type TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_entity_timestamp
                ON entities(timestamp)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_entity_species
                ON entities(species)
            """)
            # Covering index for the Entities-page aggregates (UI backend):
            # count / hourly / daily / species GROUP BY / scatter all filter a
            # timestamp range and project only these columns, so this makes
            # every one of them index-only — without it each row pays a table
            # lookup behind idx_entity_timestamp, which dominates those
            # queries' cost at production row counts.
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_entities_page_covering
                ON entities(timestamp, species, common_name, confidence)
            """)

            conn.commit()
        finally:
            conn.close()

    def save(self, detection: Detection) -> int:
        """
        Save a detection to the database.

        Serializes event_id, source_event_id, and context into the
        event_metadata JSON sidecar column for flexible persistence.

        Args:
            detection: Detection object to save

        Returns:
            Row ID of the inserted detection

        Raises:
            sqlite3.IntegrityError: If event_id already exists
        """
        conn = self._connect()
        try:
            cursor = conn.cursor()

            # Convert timestamp to ISO format string
            timestamp_str = (
                detection.timestamp.isoformat()
                if isinstance(detection.timestamp, datetime)
                else detection.timestamp
            )

            # Convert metadata dict to JSON string
            metadata_str = json.dumps(detection.metadata) if detection.metadata else "{}"

            # Build event_metadata sidecar JSON
            event_meta: dict[str, Any] = {
                "event_id": detection.event_id,
            }
            if detection.source_event_id is not None:
                event_meta["source_event_id"] = detection.source_event_id
            if detection.event_timestamp is not None:
                event_meta["event_timestamp"] = detection.event_timestamp.isoformat()
            if detection.context is not None:
                event_meta["context"] = detection.context.model_dump(mode="json")
            event_metadata_str = json.dumps(event_meta)

            # ADR 0011 — persist intervals and taxonomy in discrete columns.
            intervals_json: Optional[str] = None
            if detection.intervals is not None:
                intervals_json = json.dumps(
                    [iv.model_dump(mode="json") for iv in detection.intervals]
                )
            taxonomy_namespace: Optional[str] = None
            taxonomy_id: Optional[str] = None
            if detection.taxonomy is not None:
                taxonomy_namespace = detection.taxonomy.namespace
                taxonomy_id = detection.taxonomy.id

            cursor.execute(
                """
                INSERT INTO detections (
                    event_id, timestamp, detection_type, channel,
                    species_code, species_common, confidence,
                    audio_clip_path, metadata, source_event_id,
                    root_event_id,
                    event_metadata,
                    intervals_json, taxonomy_namespace, taxonomy_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    detection.event_id,
                    timestamp_str,
                    detection.detection_type,
                    detection.channel,
                    detection.species_code,
                    detection.species_common,
                    detection.confidence,
                    detection.audio_clip_path,
                    metadata_str,
                    detection.source_event_id,
                    detection.root_event_id,
                    event_metadata_str,
                    intervals_json,
                    taxonomy_namespace,
                    taxonomy_id,
                ),
            )

            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def query(
        self,
        detection_type: Optional[str] = None,
        species_code: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        min_confidence: Optional[float] = None,
        channel: Optional[int] = None,
        limit: int = 100,
    ) -> list[Detection]:
        """
        Query detections with filters.

        Args:
            detection_type: Filter by detection type
            species_code: Filter by species code
            start_time: Filter detections after this time
            end_time: Filter detections before this time
            min_confidence: Minimum confidence threshold
            channel: Filter by channel number
            limit: Maximum number of results

        Returns:
            List of Detection objects
        """
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()

            clause, params = self._build_filter_clause(
                detection_type=detection_type,
                species_code=species_code,
                start_time=start_time,
                end_time=end_time,
                min_confidence=min_confidence,
                channel=channel,
            )
            sql = "SELECT * FROM detections WHERE 1=1" + clause + " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)

            cursor.execute(sql, params)
            rows = cursor.fetchall()

            # Convert rows to Detection objects
            detections = []
            for row in rows:
                detections.append(self._row_to_detection(row))

            return detections
        finally:
            conn.close()

    def query_rows(
        self,
        detection_type: Optional[str] = None,
        species_code: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        min_confidence: Optional[float] = None,
        channel: Optional[int] = None,
        limit: int = 100,
    ) -> list[sqlite3.Row]:
        """``query()`` without model materialisation: same filters, same
        ``ORDER BY timestamp DESC LIMIT``, same shared ``_build_filter_clause``
        (so the paths can never drift), but returns raw ``sqlite3.Row``s.

        For aggregation consumers (the UI history/stats endpoints) that only
        read a handful of columns: building a ``Detection`` per row (Pydantic
        validation + JSON sidecar parsing for fields never read) dominates
        page-load cost at production row counts. Callers that need model
        semantics keep using :meth:`query` / :meth:`iter_query`.
        """
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            clause, params = self._build_filter_clause(
                detection_type=detection_type,
                species_code=species_code,
                start_time=start_time,
                end_time=end_time,
                min_confidence=min_confidence,
                channel=channel,
            )
            sql = (
                "SELECT * FROM detections WHERE 1=1"
                + clause
                + " ORDER BY timestamp DESC LIMIT ?"
            )
            params.append(limit)
            cursor.execute(sql, params)
            return cursor.fetchall()
        finally:
            conn.close()

    @staticmethod
    def _build_filter_clause(
        *,
        detection_type: Optional[str] = None,
        species_code: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        min_confidence: Optional[float] = None,
        channel: Optional[int] = None,
    ) -> tuple[str, list[Any]]:
        """Build the shared ``WHERE``-clause fragment + params used by both
        ``query()`` and ``iter_query()`` so the two paths can never drift.

        Returns ``(clause, params)`` where ``clause`` is appended after
        ``WHERE 1=1`` (each term is ``" AND ..."``). Timestamp bounds are
        UTC-normalised via the shared ``_iso_*_bound`` helpers so the
        lexicographic SQLite string comparison stays consistent against
        aware-stored rows (naive vs aware would otherwise misorder).
        """
        clause = ""
        params: list[Any] = []
        if detection_type:
            clause += " AND detection_type = ?"
            params.append(detection_type)
        if species_code:
            clause += " AND species_code = ?"
            params.append(species_code)
        if start_time:
            clause += " AND timestamp >= ?"
            params.append(_iso_lower_bound(start_time))
        if end_time:
            clause += " AND timestamp <= ?"
            params.append(_iso_upper_bound(end_time))
        if min_confidence is not None:
            clause += " AND confidence >= ?"
            params.append(min_confidence)
        if channel is not None:
            clause += " AND channel = ?"
            params.append(channel)
        return clause, params

    def iter_query(
        self,
        detection_type: Optional[str] = None,
        species_code: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        min_confidence: Optional[float] = None,
        channel: Optional[int] = None,
        batch_size: int = 1000,
    ) -> Iterator[Detection]:
        """Stream detections matching the filters, newest-first (same order +
        filters as :meth:`query`), yielding one ``Detection`` at a time while
        holding only ``batch_size`` rows in memory.

        Unlike :meth:`query` there is NO ``limit`` — the whole matching set is
        streamed. This is for bulk consumers (auto-discovery co-occurrence
        scans, replay) that would otherwise call ``query(limit=1_000_000)`` and
        materialise the entire window of ``Detection`` models at once — the
        all-in-memory pattern that OOM'd on the Jetson at production scale (the
        same reason ``backfill`` was rewritten to stream). The connection stays
        open for the life of the iterator; exhaust it (or let it be GC'd /
        closed) to release the connection.

        The instance's ``statement_timeout_seconds`` deliberately does NOT apply
        here: that budget is per-QUERY (connection-per-call), but this connection
        lives for the whole stream, so the budget would span the entire iteration
        and abort any legitimately long drain mid-stream (the exact caveat in
        ``_install_statement_timeout``'s contract). ``read_only`` still applies.
        """
        conn = open_connection(self.db_path, read_only=self.read_only)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            clause, params = self._build_filter_clause(
                detection_type=detection_type,
                species_code=species_code,
                start_time=start_time,
                end_time=end_time,
                min_confidence=min_confidence,
                channel=channel,
            )
            sql = "SELECT * FROM detections WHERE 1=1" + clause + " ORDER BY timestamp DESC"
            cursor.execute(sql, params)
            while True:
                rows = cursor.fetchmany(batch_size)
                if not rows:
                    break
                for row in rows:
                    yield self._row_to_detection(row)
        finally:
            conn.close()

    def count_by_hour(self, species_code: str, days: int = 7) -> list[tuple[datetime, int]]:
        """
        Count detections by hour for a species.

        Args:
            species_code: Species code to count
            days: Number of days to look back

        Returns:
            List of (hour_start, count) tuples
        """
        conn = self._connect()
        try:
            cursor = conn.cursor()

            start_time = datetime.now(timezone.utc) - timedelta(days=days)

            cursor.execute(
                """
                SELECT
                    strftime('%Y-%m-%d %H:00:00', timestamp) as hour,
                    COUNT(*) as count
                FROM detections
                WHERE species_code = ?
                  AND timestamp >= ?
                GROUP BY hour
                ORDER BY hour
            """,
                (species_code, _iso_lower_bound(start_time)),
            )

            rows = cursor.fetchall()

            # Convert to datetime objects
            results = []
            for row in rows:
                hour_dt = datetime.fromisoformat(row[0])
                count = row[1]
                results.append((hour_dt, count))

            return results
        finally:
            conn.close()

    def species_distribution(self, hours: int = 24) -> list[tuple[str, int, str]]:
        """
        Get species distribution over a time period.

        Args:
            hours: Number of hours to look back

        Returns:
            List of (species_code, count, species_common) tuples
        """
        conn = self._connect()
        try:
            cursor = conn.cursor()

            start_time = datetime.now(timezone.utc) - timedelta(hours=hours)

            cursor.execute(
                """
                SELECT
                    species_code,
                    COUNT(*) as count,
                    species_common
                FROM detections
                WHERE species_code IS NOT NULL
                  AND timestamp >= ?
                GROUP BY species_code, species_common
                ORDER BY count DESC
            """,
                (_iso_lower_bound(start_time),),
            )

            rows = cursor.fetchall()
            return [(row[0], row[1], row[2]) for row in rows]
        finally:
            conn.close()

    def get_chain(self, root_event_id: str) -> list[Detection]:
        """Return every Detection sharing the given root_event_id, ordered
        by timestamp ascending.

        This is the "metadata appended to metadata" view: the full
        downstream-enrichment chain rooted at a single audio.motion event.
        See ``docs/designs/cross-classifier-identity.md`` §1.1.

        Returns empty list if no detections match — including legacy rows
        that pre-date Layer 1.5 (their root_event_id is NULL).
        """
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM detections
                WHERE root_event_id = ?
                ORDER BY timestamp ASC
                """,
                (root_event_id,),
            )
            rows = cursor.fetchall()
            return [self._row_to_detection(row) for row in rows]
        finally:
            conn.close()

    def get_by_event_id(self, event_id: str) -> Optional[Detection]:
        """
        Get a detection by event ID.

        Args:
            event_id: Event ID to lookup

        Returns:
            Detection object or None if not found
        """
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM detections WHERE event_id = ?", (event_id,))
            row = cursor.fetchone()

            if not row:
                return None

            return self._row_to_detection(row)
        finally:
            conn.close()

    @staticmethod
    def _row_to_detection(row: sqlite3.Row) -> Detection:
        """Convert a database row to a Detection object.

        Deserializes event_metadata sidecar JSON back into the model fields
        (context, event_timestamp). Falls back gracefully if event_metadata
        is missing or NULL (pre-V2 rows).
        """
        from orpheus_common.events import SpatiotemporalContext

        metadata = json.loads(row["metadata"]) if row["metadata"] else {}

        # root_event_id added in §1.1 (cross-classifier-identity). Use
        # row.keys() check so partial-schema DBs (tests that init only
        # part of the table) don't blow up.
        root_event_id_val: Optional[str] = None
        if "root_event_id" in row.keys():
            root_event_id_val = row["root_event_id"]

        kwargs: dict[str, Any] = {
            "event_id": row["event_id"],
            "timestamp": datetime.fromisoformat(row["timestamp"]),
            "detection_type": row["detection_type"],
            "channel": row["channel"],
            "species_code": row["species_code"],
            "species_common": row["species_common"],
            "confidence": row["confidence"],
            "audio_clip_path": row["audio_clip_path"],
            "metadata": metadata,
            "source_event_id": row["source_event_id"],
            "root_event_id": root_event_id_val,
        }

        # Deserialize event_metadata sidecar if present
        event_metadata_str = row["event_metadata"] if "event_metadata" in row.keys() else None
        if event_metadata_str:
            event_meta = json.loads(event_metadata_str)
            context_data = event_meta.get("context")
            if isinstance(context_data, dict):
                kwargs["context"] = SpatiotemporalContext(**context_data)
            event_ts = event_meta.get("event_timestamp")
            if event_ts:
                kwargs["event_timestamp"] = datetime.fromisoformat(event_ts)

        # ADR 0011 — rehydrate intervals and taxonomy when present.
        intervals_str = row["intervals_json"] if "intervals_json" in row.keys() else None
        if intervals_str:
            kwargs["intervals"] = [
                TemporalInterval(**iv) for iv in json.loads(intervals_str)
            ]
        tax_ns = row["taxonomy_namespace"] if "taxonomy_namespace" in row.keys() else None
        tax_id = row["taxonomy_id"] if "taxonomy_id" in row.keys() else None
        if tax_ns and tax_id:
            kwargs["taxonomy"] = TaxonomyRef(namespace=tax_ns, id=tax_id)

        return Detection(**kwargs)

    # ------------------------------------------------------------------ #
    #  Entity persistence
    # ------------------------------------------------------------------ #

    def save_entity(self, entity: Entity) -> int:
        """Save a correlated entity to the database.

        All timestamps are normalized to UTC before storage.

        Args:
            entity: Entity object to save.

        Returns:
            Row ID of the inserted entity.

        Raises:
            sqlite3.IntegrityError: If entity_id already exists.
        """
        conn = self._connect()
        try:
            cursor = conn.cursor()

            ts = entity.timestamp
            if isinstance(ts, datetime):
                # Normalize to UTC for consistent storage
                ts = _ensure_utc(ts)
                timestamp_str = ts.isoformat()
            else:
                timestamp_str = str(ts)

            evidence_str = json.dumps([e.model_dump(mode="json") for e in entity.evidence])
            context_str = json.dumps(entity.context) if entity.context else None
            event_signature_str = (
                json.dumps(entity.event_signature) if entity.event_signature else None
            )

            cursor.execute(
                """
                INSERT INTO entities (
                    entity_id, timestamp, species, common_name,
                    confidence, evidence, context, event_signature,
                    is_self_generated, entity_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entity.entity_id,
                    timestamp_str,
                    entity.species,
                    entity.common_name,
                    entity.confidence,
                    evidence_str,
                    context_str,
                    event_signature_str,
                    1 if entity.is_self_generated else 0,
                    entity.entity_type,
                ),
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def update_entity(self, entity: Entity) -> bool:
        """Update an existing entity row in place, keyed by ``entity_id``.

        The additive counterpart to :meth:`save_entity` (whose bare INSERT raises
        ``IntegrityError`` on an existing ``entity_id`` — semantics other callers
        rely on and which are left untouched). Used by the correlator's
        late-arrival enrichment to fold new evidence into a recently-emitted
        entity instead of creating a duplicate. Updates every mutable column;
        ``created_at`` and the surrogate ``id`` stay as inserted.

        Returns:
            True if a row was updated, False if ``entity_id`` doesn't exist.
        """
        conn = self._connect()
        try:
            cursor = conn.cursor()

            ts = entity.timestamp
            if isinstance(ts, datetime):
                ts = _ensure_utc(ts)
                timestamp_str = ts.isoformat()
            else:
                timestamp_str = str(ts)

            evidence_str = json.dumps([e.model_dump(mode="json") for e in entity.evidence])
            context_str = json.dumps(entity.context) if entity.context else None
            event_signature_str = (
                json.dumps(entity.event_signature) if entity.event_signature else None
            )

            cursor.execute(
                """
                UPDATE entities SET
                    timestamp = ?, species = ?, common_name = ?,
                    confidence = ?, evidence = ?, context = ?, event_signature = ?,
                    is_self_generated = ?, entity_type = ?
                WHERE entity_id = ?
                """,
                (
                    timestamp_str,
                    entity.species,
                    entity.common_name,
                    entity.confidence,
                    evidence_str,
                    context_str,
                    event_signature_str,
                    1 if entity.is_self_generated else 0,
                    entity.entity_type,
                    entity.entity_id,
                ),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def get_entity_by_id(self, entity_id: str) -> Optional[Entity]:
        """Look up a single Entity by its ``entity_id`` (O(1) via index).

        Returns ``None`` if not found. Avoids the "fetch first N rows
        and scan in Python" pattern (which produces silent 404s when
        the target entity is older than the limit).
        """
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM entities WHERE entity_id = ? LIMIT 1",
                (entity_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return self._row_to_entity(row)
        finally:
            conn.close()

    def get_entities(
        self,
        species: Optional[str] = None,
        exclude_species: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 500,
    ) -> list[Entity]:
        """Query entities with optional filters.

        Args:
            species: Species code(s) to include.  Supports comma-separated
                values (e.g. ``"corvus,crow"``) which are expanded to an
                ``IN (?, ?)`` clause.
            exclude_species: Species code(s) to exclude.  Supports
                comma-separated values which are expanded to a
                ``NOT IN (?, ?)`` clause.
            start_time: Filter entities after this time.
            end_time: Filter entities before this time.
            limit: Maximum number of results.

        Returns:
            List of Entity objects ordered by timestamp DESC.
        """
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()

            query = "SELECT * FROM entities WHERE 1=1"
            params: list[Any] = []

            if species:
                species_list = [s.strip() for s in species.split(",") if s.strip()]
                placeholders = ",".join("?" for _ in species_list)
                # The UI's species-filter dropdown is populated from
                # `COALESCE(NULLIF(common_name,''), species)` (see
                # orpheus_ui/api/entities.py::_compute_all_species_in_range),
                # so the values arriving here can be EITHER slugs
                # (``"amerob"``) OR common names (``"American Robin"``).
                # Match against both columns so a common-name selection
                # finds the row whose slug column carries the technical
                # code. Filtering on `species` alone produced the
                # user-reported "filter shows nothing" bug.
                query += (
                    f" AND (species IN ({placeholders}) "
                    f"OR common_name IN ({placeholders}))"
                )
                params.extend(species_list)
                params.extend(species_list)

            if exclude_species:
                exclude_list = [s.strip() for s in exclude_species.split(",") if s.strip()]
                placeholders = ",".join("?" for _ in exclude_list)
                # Mirror the include change for symmetry.
                query += (
                    f" AND species NOT IN ({placeholders})"
                    f" AND (common_name IS NULL OR common_name NOT IN ({placeholders}))"
                )
                params.extend(exclude_list)
                params.extend(exclude_list)

            if start_time:
                query += " AND timestamp >= ?"
                params.append(_iso_lower_bound(start_time))

            if end_time:
                query += " AND timestamp <= ?"
                params.append(_iso_upper_bound(end_time))

            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, params)
            rows = cursor.fetchall()

            entities: list[Entity] = []
            for row in rows:
                entities.append(self._row_to_entity(row))
            return entities
        finally:
            conn.close()

    @staticmethod
    def _row_to_entity(row: sqlite3.Row) -> Entity:
        """Convert a database row to an Entity object."""
        evidence_data = json.loads(row["evidence"]) if row["evidence"] else []
        # Fail-soft: skip a malformed evidence blob rather than 500 the whole
        # query (one corrupt row must not take down the Entities page).
        evidence_list = [
            m
            for m in (
                _safe_model(EntityEvidence, e, context="entity evidence") for e in evidence_data
            )
            if m is not None
        ]

        context_data = json.loads(row["context"]) if row["context"] else None

        ts = datetime.fromisoformat(row["timestamp"])
        # Ensure UTC awareness when reading back from the DB
        ts = _ensure_utc(ts)

        # Layer 2 — event_signature is optional; legacy rows have NULL.
        event_signature_data = None
        if "event_signature" in row.keys() and row["event_signature"]:
            event_signature_data = json.loads(row["event_signature"])

        # Corollary discharge — additive column; legacy rows lack it → False.
        is_self_generated = False
        if "is_self_generated" in row.keys() and row["is_self_generated"] is not None:
            is_self_generated = bool(row["is_self_generated"])

        # Entity-type taxonomy — additive nullable column; legacy rows → None.
        entity_type = None
        if "entity_type" in row.keys() and row["entity_type"] is not None:
            entity_type = str(row["entity_type"])

        return Entity(
            entity_id=row["entity_id"],
            timestamp=ts,
            species=row["species"],
            common_name=row["common_name"] or "",
            confidence=row["confidence"] or 0.0,
            evidence=evidence_list,
            context=context_data,
            event_signature=event_signature_data,
            is_self_generated=is_self_generated,
            entity_type=entity_type,
        )
