"""Tests for DetectionDB and Detection models."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from orpheus_common.detection import Detection, DetectionDB, Entity, EntityEvidence


class TestDetection:
    """Tests for Detection data model."""

    def test_detection_creation(self) -> None:
        """Should create Detection with required fields."""
        detection = Detection(
            event_id="test_001",
            timestamp=datetime(2025, 12, 5, 12, 0, 0),
            detection_type="species.detected",
        )
        assert detection.event_id == "test_001"
        assert detection.timestamp == datetime(2025, 12, 5, 12, 0, 0)
        assert detection.detection_type == "species.detected"
        assert detection.channel is None
        assert detection.species_code is None

    def test_detection_with_all_fields(self) -> None:
        """Should create Detection with all fields."""
        metadata = {"extra": "data"}
        detection = Detection(
            event_id="test_002",
            timestamp=datetime(2025, 12, 5, 12, 0, 0),
            detection_type="species.detected",
            channel=1,
            species_code="amecro",
            species_common="American Crow",
            confidence=0.95,
            audio_clip_path="/data/orpheus/audio/test.flac",
            metadata=metadata,
            source_event_id="audio_motion_001",
        )
        assert detection.channel == 1
        assert detection.species_code == "amecro"
        assert detection.species_common == "American Crow"
        assert detection.confidence == 0.95
        assert detection.audio_clip_path == "/data/orpheus/audio/test.flac"
        assert detection.metadata == metadata
        assert detection.source_event_id == "audio_motion_001"

    def test_detection_to_dict(self) -> None:
        """Should convert Detection to dict."""
        detection = Detection(
            event_id="test_003",
            timestamp=datetime(2025, 12, 5, 12, 0, 0),
            detection_type="species.detected",
            species_code="amecro",
            confidence=0.88,
        )
        data = detection.to_dict()
        assert data["event_id"] == "test_003"
        assert data["detection_type"] == "species.detected"
        assert data["species_code"] == "amecro"
        assert data["confidence"] == 0.88

    def test_detection_from_dict(self) -> None:
        """Should create Detection from dict."""
        data = {
            "event_id": "test_004",
            "timestamp": "2025-12-05T12:00:00",
            "detection_type": "audio.motion",
            "channel": 2,
            "species_code": None,
            "species_common": None,
            "confidence": None,
            "audio_clip_path": "/data/test.flac",
            "metadata": {"foo": "bar"},
            "source_event_id": None,
        }
        detection = Detection.from_dict(data)
        assert detection.event_id == "test_004"
        assert detection.timestamp == datetime(2025, 12, 5, 12, 0, 0)
        assert detection.channel == 2
        assert detection.metadata == {"foo": "bar"}


class TestDetectionDB:
    """Tests for DetectionDB."""

    @pytest.fixture
    def db(self, tmp_path: Path) -> DetectionDB:
        """Create temporary database for testing."""
        db_path = tmp_path / "test.db"
        return DetectionDB(db_path=db_path)

    def test_db_init_creates_schema(self, tmp_path: Path) -> None:
        """Should create database file and schema."""
        db_path = tmp_path / "test.db"
        DetectionDB(db_path=db_path)
        assert db_path.exists()

    def test_save_detection(self, db: DetectionDB) -> None:
        """Should save detection to database."""
        detection = Detection(
            event_id="save_001",
            timestamp=datetime.now(timezone.utc),
            detection_type="species.detected",
            species_code="amecro",
            confidence=0.91,
        )
        row_id = db.save(detection)
        assert row_id > 0

    def test_save_duplicate_event_id_raises_error(self, db: DetectionDB) -> None:
        """Should raise error when saving duplicate event_id."""
        detection1 = Detection(
            event_id="dup_001",
            timestamp=datetime.now(timezone.utc),
            detection_type="species.detected",
        )
        db.save(detection1)

        detection2 = Detection(
            event_id="dup_001",
            timestamp=datetime.now(timezone.utc),
            detection_type="species.detected",
        )
        with pytest.raises(Exception):  # sqlite3.IntegrityError
            db.save(detection2)

    def test_get_by_event_id(self, db: DetectionDB) -> None:
        """Should retrieve detection by event_id."""
        detection = Detection(
            event_id="get_001",
            timestamp=datetime(2025, 12, 5, 12, 0, 0),
            detection_type="species.detected",
            species_code="amecro",
            confidence=0.85,
        )
        db.save(detection)

        result = db.get_by_event_id("get_001")
        assert result is not None
        assert result.event_id == "get_001"
        assert result.species_code == "amecro"
        assert result.confidence == 0.85

    def test_get_by_event_id_not_found(self, db: DetectionDB) -> None:
        """Should return None for non-existent event_id."""
        result = db.get_by_event_id("nonexistent")
        assert result is None

    def test_query_all(self, db: DetectionDB) -> None:
        """Should query all detections."""
        for i in range(5):
            detection = Detection(
                event_id=f"query_all_{i}",
                timestamp=datetime.now(timezone.utc),
                detection_type="species.detected",
            )
            db.save(detection)

        results = db.query(limit=10)
        assert len(results) == 5

    def test_query_by_detection_type(self, db: DetectionDB) -> None:
        """Should filter by detection_type."""
        db.save(
            Detection(
                event_id="type1",
                timestamp=datetime.now(timezone.utc),
                detection_type="audio.motion",
            )
        )
        db.save(
            Detection(
                event_id="type2",
                timestamp=datetime.now(timezone.utc),
                detection_type="species.detected",
            )
        )
        db.save(
            Detection(
                event_id="type3",
                timestamp=datetime.now(timezone.utc),
                detection_type="species.detected",
            )
        )

        results = db.query(detection_type="species.detected")
        assert len(results) == 2

    def test_query_by_species_code(self, db: DetectionDB) -> None:
        """Should filter by species_code."""
        db.save(
            Detection(
                event_id="sp1",
                timestamp=datetime.now(timezone.utc),
                detection_type="species.detected",
                species_code="amecro",
            )
        )
        db.save(
            Detection(
                event_id="sp2",
                timestamp=datetime.now(timezone.utc),
                detection_type="species.detected",
                species_code="comrav",
            )
        )
        db.save(
            Detection(
                event_id="sp3",
                timestamp=datetime.now(timezone.utc),
                detection_type="species.detected",
                species_code="amecro",
            )
        )

        results = db.query(species_code="amecro")
        assert len(results) == 2

    def test_query_by_time_range(self, db: DetectionDB) -> None:
        """Should filter by time range."""
        now = datetime.now(timezone.utc)
        db.save(
            Detection(
                event_id="t1", timestamp=now - timedelta(hours=2), detection_type="species.detected"
            )
        )
        db.save(
            Detection(
                event_id="t2", timestamp=now - timedelta(hours=1), detection_type="species.detected"
            )
        )
        db.save(Detection(event_id="t3", timestamp=now, detection_type="species.detected"))

        results = db.query(start_time=now - timedelta(hours=1, minutes=30))
        assert len(results) == 2

    def test_query_by_confidence(self, db: DetectionDB) -> None:
        """Should filter by minimum confidence."""
        db.save(
            Detection(
                event_id="conf1",
                timestamp=datetime.now(timezone.utc),
                detection_type="species.detected",
                confidence=0.5,
            )
        )
        db.save(
            Detection(
                event_id="conf2",
                timestamp=datetime.now(timezone.utc),
                detection_type="species.detected",
                confidence=0.8,
            )
        )
        db.save(
            Detection(
                event_id="conf3",
                timestamp=datetime.now(timezone.utc),
                detection_type="species.detected",
                confidence=0.9,
            )
        )

        results = db.query(min_confidence=0.75)
        assert len(results) == 2

    def test_query_by_channel(self, db: DetectionDB) -> None:
        """Should filter by channel."""
        db.save(
            Detection(
                event_id="ch1",
                timestamp=datetime.now(timezone.utc),
                detection_type="audio.motion",
                channel=1,
            )
        )
        db.save(
            Detection(
                event_id="ch2",
                timestamp=datetime.now(timezone.utc),
                detection_type="audio.motion",
                channel=2,
            )
        )
        db.save(
            Detection(
                event_id="ch3",
                timestamp=datetime.now(timezone.utc),
                detection_type="audio.motion",
                channel=1,
            )
        )

        results = db.query(channel=1)
        assert len(results) == 2

    def test_query_limit(self, db: DetectionDB) -> None:
        """Should respect limit parameter."""
        for i in range(10):
            db.save(
                Detection(
                    event_id=f"lim_{i}",
                    timestamp=datetime.now(timezone.utc),
                    detection_type="species.detected",
                )
            )

        results = db.query(limit=5)
        assert len(results) == 5

    def test_count_by_hour(self, db: DetectionDB) -> None:
        """Should count detections by hour."""
        now = datetime.now(timezone.utc)
        base_time = now.replace(minute=0, second=0, microsecond=0)

        # Add detections across different hours
        for i in range(3):
            db.save(
                Detection(
                    event_id=f"hour_{i}_1",
                    timestamp=base_time - timedelta(hours=i),
                    detection_type="species.detected",
                    species_code="amecro",
                )
            )
            db.save(
                Detection(
                    event_id=f"hour_{i}_2",
                    timestamp=base_time - timedelta(hours=i),
                    detection_type="species.detected",
                    species_code="amecro",
                )
            )

        results = db.count_by_hour("amecro", days=1)
        assert len(results) == 3
        # Each hour should have 2 detections
        for hour_dt, count in results:
            assert count == 2

    def test_species_distribution(self, db: DetectionDB) -> None:
        """Should get species distribution."""
        now = datetime.now(timezone.utc)

        # Add multiple species
        for _ in range(3):
            db.save(
                Detection(
                    event_id=f"dist_amecro_{_}",
                    timestamp=now,
                    detection_type="species.detected",
                    species_code="amecro",
                    species_common="American Crow",
                )
            )

        for _ in range(2):
            db.save(
                Detection(
                    event_id=f"dist_comrav_{_}",
                    timestamp=now,
                    detection_type="species.detected",
                    species_code="comrav",
                    species_common="Common Raven",
                )
            )

        results = db.species_distribution(hours=1)
        assert len(results) == 2

        # Results should be ordered by count DESC
        assert results[0][0] == "amecro"  # species_code
        assert results[0][1] == 3  # count
        assert results[0][2] == "American Crow"  # species_common

        assert results[1][0] == "comrav"
        assert results[1][1] == 2

    def test_save_with_metadata(self, db: DetectionDB) -> None:
        """Should save and retrieve detection with metadata."""
        metadata = {"model_version": "BirdNET_V2.4", "inference_time_ms": 145}
        detection = Detection(
            event_id="meta_001",
            timestamp=datetime.now(timezone.utc),
            detection_type="species.detected",
            metadata=metadata,
        )
        db.save(detection)

        result = db.get_by_event_id("meta_001")
        assert result is not None
        assert result.metadata == metadata


class TestEntity:
    """Tests for Entity data model."""

    def test_entity_creation(self) -> None:
        """Should create Entity with required fields."""
        entity = Entity(
            entity_id="ent_001",
            timestamp=datetime(2025, 12, 5, 12, 0, 0),
            species="amecro",
            common_name="American Crow",
            confidence=0.95,
        )
        assert entity.entity_id == "ent_001"
        assert entity.species == "amecro"
        assert entity.common_name == "American Crow"
        assert entity.confidence == 0.95
        assert entity.evidence == []

    def test_entity_with_evidence(self) -> None:
        """Should create Entity with evidence list."""
        evidence = [
            EntityEvidence(event_id="det_1", sensor_id="mic-1", confidence=0.9),
            EntityEvidence(event_id="det_2", sensor_id="mic-2", confidence=0.85),
        ]
        entity = Entity(
            entity_id="ent_002",
            timestamp=datetime(2025, 12, 5, 12, 0, 0),
            species="amecro",
            evidence=evidence,
        )
        assert len(entity.evidence) == 2
        assert entity.evidence[0].event_id == "det_1"
        assert entity.evidence[1].sensor_id == "mic-2"

    def test_entity_to_dict(self) -> None:
        """Should convert Entity to dict."""
        entity = Entity(
            entity_id="ent_003",
            timestamp=datetime(2025, 12, 5, 12, 0, 0),
            species="amecro",
            common_name="American Crow",
            confidence=0.88,
        )
        data = entity.to_dict()
        assert data["entity_id"] == "ent_003"
        assert data["species"] == "amecro"
        assert data["confidence"] == 0.88
        assert data["evidence"] == []

    def test_entity_from_entity_event(self) -> None:
        """Should create Entity from ClusterManager entity event dict."""
        event = {
            "entity_id": "ent_004",
            "timestamp": "2025-12-05T12:00:00",
            "species_code": "amecro",
            "common_name": "American Crow",
            "confidence": 0.92,
            "context": {"lat": 47.6, "lon": -122.3},
            "evidence": [
                {"event_id": "det_a", "sensor_id": "mic-1", "confidence": 0.92},
                {"event_id": "det_b", "sensor_id": "mic-2", "confidence": 0.88},
            ],
        }
        entity = Entity.from_entity_event(event)
        assert entity.entity_id == "ent_004"
        assert entity.species == "amecro"
        assert entity.common_name == "American Crow"
        assert len(entity.evidence) == 2


class TestEntityDB:
    """Tests for Entity persistence in DetectionDB."""

    @pytest.fixture
    def db(self, tmp_path: Path) -> DetectionDB:
        """Create temporary database for testing."""
        db_path = tmp_path / "test.db"
        return DetectionDB(db_path=db_path)

    def test_save_entity(self, db: DetectionDB) -> None:
        """Should save entity to database."""
        entity = Entity(
            entity_id="ent_save_001",
            timestamp=datetime.now(timezone.utc),
            species="amecro",
            common_name="American Crow",
            confidence=0.91,
            evidence=[
                EntityEvidence(event_id="d1", sensor_id="mic-1", confidence=0.91),
            ],
        )
        row_id = db.save_entity(entity)
        assert row_id > 0

    def test_save_duplicate_entity_id_raises_error(self, db: DetectionDB) -> None:
        """Should raise error when saving duplicate entity_id."""
        entity1 = Entity(
            entity_id="ent_dup_001",
            timestamp=datetime.now(timezone.utc),
            species="amecro",
        )
        db.save_entity(entity1)

        entity2 = Entity(
            entity_id="ent_dup_001",
            timestamp=datetime.now(timezone.utc),
            species="amecro",
        )
        with pytest.raises(Exception):
            db.save_entity(entity2)

    def test_get_entities_all(self, db: DetectionDB) -> None:
        """Should query all entities."""
        for i in range(5):
            db.save_entity(
                Entity(
                    entity_id=f"ent_all_{i}",
                    timestamp=datetime.now(timezone.utc),
                    species="amecro",
                )
            )

        results = db.get_entities()
        assert len(results) == 5

    def test_get_entities_by_species(self, db: DetectionDB) -> None:
        """Should filter entities by species."""
        db.save_entity(
            Entity(
                entity_id="ent_sp1",
                timestamp=datetime.now(timezone.utc),
                species="amecro",
            )
        )
        db.save_entity(
            Entity(
                entity_id="ent_sp2",
                timestamp=datetime.now(timezone.utc),
                species="comrav",
            )
        )
        db.save_entity(
            Entity(
                entity_id="ent_sp3",
                timestamp=datetime.now(timezone.utc),
                species="amecro",
            )
        )

        results = db.get_entities(species="amecro")
        assert len(results) == 2

    def test_get_entities_exclude_species(self, db: DetectionDB) -> None:
        """Should exclude entities by species."""
        db.save_entity(
            Entity(
                entity_id="ent_ex1",
                timestamp=datetime.now(timezone.utc),
                species="amecro",
            )
        )
        db.save_entity(
            Entity(
                entity_id="ent_ex2",
                timestamp=datetime.now(timezone.utc),
                species="comrav",
            )
        )

        results = db.get_entities(exclude_species="amecro")
        assert len(results) == 1
        assert results[0].species == "comrav"

    def test_get_entities_comma_separated_species(self, db: DetectionDB) -> None:
        """Should filter entities by comma-separated species codes."""
        db.save_entity(
            Entity(
                entity_id="ent_csv1",
                timestamp=datetime.now(timezone.utc),
                species="corvus",
            )
        )
        db.save_entity(
            Entity(
                entity_id="ent_csv2",
                timestamp=datetime.now(timezone.utc),
                species="crow",
            )
        )
        db.save_entity(
            Entity(
                entity_id="ent_csv3",
                timestamp=datetime.now(timezone.utc),
                species="amecro",
            )
        )

        results = db.get_entities(species="corvus,crow")
        assert len(results) == 2
        species_set = {r.species for r in results}
        assert species_set == {"corvus", "crow"}

    def test_get_entities_comma_separated_exclude(self, db: DetectionDB) -> None:
        """Should exclude entities by comma-separated species codes."""
        db.save_entity(
            Entity(
                entity_id="ent_csx1",
                timestamp=datetime.now(timezone.utc),
                species="corvus",
            )
        )
        db.save_entity(
            Entity(
                entity_id="ent_csx2",
                timestamp=datetime.now(timezone.utc),
                species="crow",
            )
        )
        db.save_entity(
            Entity(
                entity_id="ent_csx3",
                timestamp=datetime.now(timezone.utc),
                species="song_s",
            )
        )

        results = db.get_entities(exclude_species="corvus,crow")
        assert len(results) == 1
        assert results[0].species == "song_s"

    def test_get_entities_by_time_range(self, db: DetectionDB) -> None:
        """Should filter entities by time range."""
        now = datetime.now(timezone.utc)
        db.save_entity(
            Entity(entity_id="ent_t1", timestamp=now - timedelta(hours=2), species="amecro")
        )
        db.save_entity(
            Entity(entity_id="ent_t2", timestamp=now - timedelta(hours=1), species="amecro")
        )
        db.save_entity(Entity(entity_id="ent_t3", timestamp=now, species="amecro"))

        results = db.get_entities(start_time=now - timedelta(hours=1, minutes=30))
        assert len(results) == 2

    def test_get_entities_end_date_inclusive(self, db: DetectionDB) -> None:
        """Should include entities from the entire end_date day (end of day: 23:59:59)."""
        # Create entities at different times on the same UTC date
        date = datetime(2026, 2, 17, tzinfo=timezone.utc)

        # Entity at 10:00 AM UTC
        db.save_entity(
            Entity(
                entity_id="ent_morning",
                timestamp=date.replace(hour=10, minute=0, second=0),
                species="corvus",
            )
        )

        # Entity at 7:37 PM UTC (19:37)
        db.save_entity(
            Entity(
                entity_id="ent_evening",
                timestamp=date.replace(hour=19, minute=37, second=24),
                species="crow",
            )
        )

        # Entity at 11:59 PM UTC (almost midnight)
        db.save_entity(
            Entity(
                entity_id="ent_late",
                timestamp=date.replace(hour=23, minute=59, second=59),
                species="corvus",
            )
        )

        # Entity the next day (should be excluded)
        db.save_entity(
            Entity(
                entity_id="ent_next_day",
                timestamp=date + timedelta(days=1),
                species="corvus",
            )
        )

        # Query with end_time set to end of day (23:59:59.999999)
        end_time = date.replace(hour=23, minute=59, second=59, microsecond=999999)
        results = db.get_entities(end_time=end_time)

        # Should get all 3 entities from 2026-02-17, but not the next day
        assert len(results) == 3
        entity_ids = {e.entity_id for e in results}
        assert entity_ids == {"ent_morning", "ent_evening", "ent_late"}

    def test_get_entities_preserves_evidence(self, db: DetectionDB) -> None:
        """Should round-trip evidence through save/get."""
        entity = Entity(
            entity_id="ent_ev1",
            timestamp=datetime.now(timezone.utc),
            species="amecro",
            common_name="American Crow",
            confidence=0.95,
            evidence=[
                EntityEvidence(event_id="d1", sensor_id="mic-1", confidence=0.95),
                EntityEvidence(event_id="d2", sensor_id="mic-2", confidence=0.88),
            ],
            context={"lat": 47.6, "lon": -122.3},
        )
        db.save_entity(entity)

        results = db.get_entities(species="amecro")
        assert len(results) == 1
        result = results[0]
        assert result.entity_id == "ent_ev1"
        assert result.common_name == "American Crow"
        assert result.confidence == 0.95
        assert len(result.evidence) == 2
        assert result.evidence[0].sensor_id == "mic-1"
        assert result.context["lat"] == 47.6
