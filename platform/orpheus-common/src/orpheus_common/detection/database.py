"""SQLite database for storing detection events."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from orpheus_common.storage import get_data_root

from .models import Detection, Entity, EntityEvidence


def _ensure_utc(dt: datetime) -> datetime:
    """Normalize a datetime to UTC.  Treats naive datetimes as UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def ensure_schema_updates(db_path: Path) -> None:
    """
    Safely migrate the database schema by adding new columns if missing.

    This runs on startup and uses ALTER TABLE to add columns that don't exist.
    SQLite ignores extra columns when reading with old code, making rollbacks safe.

    Args:
        db_path: Path to the SQLite database file.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.cursor()
        # Check existing columns
        cursor.execute("PRAGMA table_info(detections)")
        existing_columns = {row[1] for row in cursor.fetchall()}

        if "event_metadata" not in existing_columns:
            cursor.execute("ALTER TABLE detections ADD COLUMN event_metadata TEXT")
            conn.commit()
    finally:
        conn.close()


class DetectionDB:
    """
    SQLite database for storing and querying detection events.

    Default location: /data/orpheus/detections/orpheus.db
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        """
        Initialize DetectionDB.

        Args:
            db_path: Path to SQLite database file. If None, uses default location.
        """
        if db_path is None:
            detections_dir = get_data_root() / "detections"
            detections_dir.mkdir(parents=True, exist_ok=True)
            db_path = detections_dir / "orpheus.db"

        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._init_schema()
        ensure_schema_updates(self.db_path)

    def _init_schema(self) -> None:
        """Initialize database schema."""
        conn = sqlite3.connect(str(self.db_path))
        try:
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

            # Entity table for correlated events
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
        conn = sqlite3.connect(str(self.db_path))
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

            cursor.execute(
                """
                INSERT INTO detections (
                    event_id, timestamp, detection_type, channel,
                    species_code, species_common, confidence,
                    audio_clip_path, metadata, source_event_id,
                    event_metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    event_metadata_str,
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
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()

            # Build query dynamically based on filters
            query = "SELECT * FROM detections WHERE 1=1"
            params: list[Any] = []

            if detection_type:
                query += " AND detection_type = ?"
                params.append(detection_type)

            if species_code:
                query += " AND species_code = ?"
                params.append(species_code)

            if start_time:
                query += " AND timestamp >= ?"
                # Remove microseconds to ensure proper string comparison in SQLite
                params.append(start_time.replace(microsecond=0).isoformat())

            if end_time:
                query += " AND timestamp <= ?"
                # Set microseconds to max to ensure proper string comparison in SQLite
                params.append(end_time.replace(microsecond=999999).isoformat())

            if min_confidence is not None:
                query += " AND confidence >= ?"
                params.append(min_confidence)

            if channel is not None:
                query += " AND channel = ?"
                params.append(channel)

            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, params)
            rows = cursor.fetchall()

            # Convert rows to Detection objects
            detections = []
            for row in rows:
                detections.append(self._row_to_detection(row))

            return detections
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
        conn = sqlite3.connect(str(self.db_path))
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
                (species_code, start_time.isoformat()),
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
        conn = sqlite3.connect(str(self.db_path))
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
                (start_time.isoformat(),),
            )

            rows = cursor.fetchall()
            return [(row[0], row[1], row[2]) for row in rows]
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
        conn = sqlite3.connect(str(self.db_path))
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
        conn = sqlite3.connect(str(self.db_path))
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

            cursor.execute(
                """
                INSERT INTO entities (
                    entity_id, timestamp, species, common_name,
                    confidence, evidence, context
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entity.entity_id,
                    timestamp_str,
                    entity.species,
                    entity.common_name,
                    entity.confidence,
                    evidence_str,
                    context_str,
                ),
            )
            conn.commit()
            return cursor.lastrowid
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
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()

            query = "SELECT * FROM entities WHERE 1=1"
            params: list[Any] = []

            if species:
                species_list = [s.strip() for s in species.split(",") if s.strip()]
                placeholders = ",".join("?" for _ in species_list)
                query += f" AND species IN ({placeholders})"
                params.extend(species_list)

            if exclude_species:
                exclude_list = [s.strip() for s in exclude_species.split(",") if s.strip()]
                placeholders = ",".join("?" for _ in exclude_list)
                query += f" AND species NOT IN ({placeholders})"
                params.extend(exclude_list)

            if start_time:
                query += " AND timestamp >= ?"
                params.append(_ensure_utc(start_time).replace(microsecond=0).isoformat())

            if end_time:
                query += " AND timestamp <= ?"
                params.append(_ensure_utc(end_time).replace(microsecond=999999).isoformat())

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
        evidence_list = [EntityEvidence(**e) for e in evidence_data]

        context_data = json.loads(row["context"]) if row["context"] else None

        ts = datetime.fromisoformat(row["timestamp"])
        # Ensure UTC awareness when reading back from the DB
        ts = _ensure_utc(ts)

        return Entity(
            entity_id=row["entity_id"],
            timestamp=ts,
            species=row["species"],
            common_name=row["common_name"] or "",
            confidence=row["confidence"] or 0.0,
            evidence=evidence_list,
            context=context_data,
        )
