"""Integration tests for event persistence with JSON sidecar column."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from orpheus_common.detection import Detection, DetectionDB
from orpheus_common.events import SpatiotemporalContext


class TestEventPersistenceRoundTrip:
    """Test saving and loading events with the event_metadata JSON sidecar."""

    @pytest.fixture
    def db(self, tmp_path: Path) -> DetectionDB:
        """Create a temporary database for testing."""
        db_path = tmp_path / "test_events.db"
        return DetectionDB(db_path=db_path)

    def test_save_and_load_with_context(self, db: DetectionDB) -> None:
        """Full V2 event with GPS context should round-trip through SQLite."""
        ctx = SpatiotemporalContext(lat=47.6062, lon=-122.3321, elevation=56.0, sensor_id="mic-01")
        detection = Detection(
            event_id="roundtrip_001",
            timestamp=datetime(2025, 12, 5, 12, 0, 0, tzinfo=timezone.utc),
            detection_type="species.detected",
            species_code="amecro",
            species_common="American Crow",
            confidence=0.95,
            channel=1,
            source_event_id="audio_motion_001",
            context=ctx,
        )
        db.save(detection)

        # Reload from DB
        loaded = db.get_by_event_id("roundtrip_001")
        assert loaded is not None
        assert loaded.event_id == "roundtrip_001"
        assert loaded.species_code == "amecro"
        assert loaded.confidence == 0.95
        assert loaded.source_event_id == "audio_motion_001"

        # Verify GPS coordinates survived the round-trip
        assert loaded.context is not None
        assert loaded.context.lat == 47.6062
        assert loaded.context.lon == -122.3321
        assert loaded.context.elevation == 56.0
        assert loaded.context.sensor_id == "mic-01"

    def test_save_and_load_without_context(self, db: DetectionDB) -> None:
        """Event without context should round-trip (backward compat)."""
        detection = Detection(
            event_id="roundtrip_002",
            timestamp=datetime(2025, 12, 5, 12, 0, 0, tzinfo=timezone.utc),
            detection_type="audio.motion",
        )
        db.save(detection)

        loaded = db.get_by_event_id("roundtrip_002")
        assert loaded is not None
        assert loaded.event_id == "roundtrip_002"
        assert loaded.context is None

    def test_close_and_reopen_db(self, tmp_path: Path) -> None:
        """Data should persist across DB close/reopen."""
        db_path = tmp_path / "persist_test.db"

        # Create and save
        db1 = DetectionDB(db_path=db_path)
        ctx = SpatiotemporalContext(lat=34.0522, lon=-118.2437, sensor_id="mic-02")
        detection = Detection(
            event_id="persist_001",
            timestamp=datetime(2025, 12, 5, 12, 0, 0, tzinfo=timezone.utc),
            detection_type="species.detected",
            species_code="comrav",
            confidence=0.88,
            context=ctx,
        )
        db1.save(detection)
        del db1  # Close

        # Reopen and verify
        db2 = DetectionDB(db_path=db_path)
        loaded = db2.get_by_event_id("persist_001")
        assert loaded is not None
        assert loaded.species_code == "comrav"
        assert loaded.context is not None
        assert loaded.context.lat == 34.0522
        assert loaded.context.lon == -118.2437

    def test_query_returns_context(self, db: DetectionDB) -> None:
        """Query results should include deserialized context."""
        ctx = SpatiotemporalContext(lat=47.6, lon=-122.3, sensor_id="mic-01")
        detection = Detection(
            event_id="query_ctx_001",
            timestamp=datetime.now(timezone.utc),
            detection_type="species.detected",
            species_code="amecro",
            confidence=0.9,
            context=ctx,
        )
        db.save(detection)

        results = db.query(species_code="amecro")
        assert len(results) == 1
        assert results[0].context is not None
        assert results[0].context.lat == 47.6


class TestEnsureSchemaUpdates:
    """Test the safe migration function."""

    def test_adds_event_metadata_column(self, tmp_path: Path) -> None:
        """ensure_schema_updates should add event_metadata if missing."""
        import sqlite3

        from orpheus_common.detection.database import ensure_schema_updates

        db_path = tmp_path / "migrate_test.db"

        # Create a V1 schema (no event_metadata)
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE detections (
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
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()

        # Run migration
        ensure_schema_updates(db_path)

        # Verify column was added
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("PRAGMA table_info(detections)")
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()

        assert "event_metadata" in columns

    def test_idempotent_migration(self, tmp_path: Path) -> None:
        """Running ensure_schema_updates twice should not error."""
        from orpheus_common.detection.database import ensure_schema_updates

        db_path = tmp_path / "idempotent_test.db"
        DetectionDB(db_path=db_path)  # Creates schema with event_metadata

        # Running again should be safe
        ensure_schema_updates(db_path)
        ensure_schema_updates(db_path)  # Third time
