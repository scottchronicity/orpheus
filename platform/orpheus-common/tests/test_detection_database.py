"""Tests for DetectionDB and Detection models."""

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from orpheus_common.detection import (
    Detection,
    DetectionDB,
    Entity,
    EntityEvidence,
    TaxonomyRef,
    TemporalInterval,
)
from orpheus_common.detection.database import (
    _iso_lower_bound,
    _iso_upper_bound,
    _safe_model,
    open_connection,
)


class TestOpenConnectionReadOnly:
    """read_only=True is the data-layer floor for read-only consumers (the
    read-only mirror/replica + the LLM-facing observability surface): reads
    work, every write raises instead of mutating the file."""

    def test_default_connection_can_write(self, tmp_path: Path) -> None:
        conn = open_connection(tmp_path / "rw.db")
        try:
            conn.execute("CREATE TABLE t (x INTEGER)")
            conn.execute("INSERT INTO t VALUES (1)")
            conn.commit()
            assert conn.execute("SELECT x FROM t").fetchone()[0] == 1
        finally:
            conn.close()

    def test_read_only_can_read(self, tmp_path: Path) -> None:
        db = tmp_path / "ro.db"
        w = open_connection(db)
        w.execute("CREATE TABLE t (x INTEGER)")
        w.execute("INSERT INTO t VALUES (42)")
        w.commit()
        w.close()

        ro = open_connection(db, read_only=True)
        try:
            assert ro.execute("SELECT x FROM t").fetchone()[0] == 42
        finally:
            ro.close()

    def test_read_only_rejects_writes(self, tmp_path: Path) -> None:
        db = tmp_path / "ro2.db"
        w = open_connection(db)
        w.execute("CREATE TABLE t (x INTEGER)")
        w.commit()
        w.close()

        ro = open_connection(db, read_only=True)
        try:
            with pytest.raises(sqlite3.OperationalError, match="readonly"):
                ro.execute("INSERT INTO t VALUES (1)")
            with pytest.raises(sqlite3.OperationalError, match="readonly"):
                ro.execute("CREATE TABLE u (y INTEGER)")
        finally:
            ro.close()


class TestDetectionDBReadOnly:
    """A read_only DetectionDB (the replica path) serves reads and rejects every
    write, and never creates or migrates the file."""

    def _populate(self, path: Path) -> None:
        db = DetectionDB(db_path=path)
        db.save(
            Detection(
                event_id="e1",
                timestamp=datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
                detection_type="species.detected",
                species_code="amecro",
            )
        )

    def test_read_only_serves_reads(self, tmp_path: Path) -> None:
        path = tmp_path / "d.db"
        self._populate(path)
        ro = DetectionDB(db_path=path, read_only=True)
        assert ro.read_only is True
        got = ro.get_by_event_id("e1")
        assert got is not None and got.species_code == "amecro"

    def test_read_only_rejects_save(self, tmp_path: Path) -> None:
        path = tmp_path / "d.db"
        self._populate(path)
        ro = DetectionDB(db_path=path, read_only=True)
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            ro.save(
                Detection(
                    event_id="e2",
                    timestamp=datetime(2025, 1, 1, 12, 0, 1, tzinfo=timezone.utc),
                    detection_type="species.detected",
                )
            )

    def test_read_only_does_not_create_or_migrate(self, tmp_path: Path) -> None:
        # Construction must not create the file or run a writer (schema init).
        missing = tmp_path / "missing.db"
        db = DetectionDB(db_path=missing, read_only=True)
        assert not missing.exists()
        # The first query opens mode=ro on the absent file and raises — it never
        # silently creates an empty DB the way a writer connection would.
        with pytest.raises(sqlite3.OperationalError):
            db.get_by_event_id("x")


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

    def test_detection_defaults_intervals_and_taxonomy_to_none(self) -> None:
        """Legacy callers that don't pass intervals/taxonomy should get None."""
        detection = Detection(
            timestamp=datetime(2025, 12, 5, 12, 0, 0),
            detection_type="species.detected",
        )
        assert detection.intervals is None
        assert detection.taxonomy is None

    def test_detection_with_intervals(self) -> None:
        """Should accept a list of TemporalInterval on construction."""
        intervals = [
            TemporalInterval(start_seconds=0.5, end_seconds=1.2, confidence=0.8),
            TemporalInterval(start_seconds=4.0, end_seconds=5.1),
        ]
        detection = Detection(
            timestamp=datetime(2025, 12, 5, 12, 0, 0),
            detection_type="audio.classified",
            intervals=intervals,
        )
        assert detection.intervals is not None
        assert len(detection.intervals) == 2
        assert detection.intervals[0].start_seconds == 0.5
        assert detection.intervals[0].end_seconds == 1.2
        assert detection.intervals[0].confidence == 0.8
        assert detection.intervals[1].confidence is None

    def test_detection_with_taxonomy(self) -> None:
        """Should accept a TaxonomyRef on construction."""
        detection = Detection(
            timestamp=datetime(2025, 12, 5, 12, 0, 0),
            detection_type="audio.classified",
            taxonomy=TaxonomyRef(
                namespace="audioset",
                id="/m/04rlf",
                common_name="Music",
            ),
        )
        assert detection.taxonomy is not None
        assert detection.taxonomy.namespace == "audioset"
        assert detection.taxonomy.id == "/m/04rlf"
        assert detection.taxonomy.common_name == "Music"

    def test_detection_to_dict_with_intervals(self) -> None:
        """to_dict() should serialise intervals to a list of plain dicts."""
        detection = Detection(
            event_id="loc_001",
            timestamp=datetime(2025, 12, 5, 12, 0, 0),
            detection_type="audio.classified",
            intervals=[
                TemporalInterval(start_seconds=1.0, end_seconds=2.0, confidence=0.7),
            ],
        )
        data = detection.to_dict()
        assert data["intervals"] == [
            {"start_seconds": 1.0, "end_seconds": 2.0, "confidence": 0.7}
        ]

    def test_detection_to_dict_with_taxonomy(self) -> None:
        """to_dict() should serialise taxonomy to a plain dict."""
        detection = Detection(
            event_id="tax_001",
            timestamp=datetime(2025, 12, 5, 12, 0, 0),
            detection_type="audio.classified",
            taxonomy=TaxonomyRef(namespace="audioset", id="/m/04rlf"),
        )
        data = detection.to_dict()
        assert data["taxonomy"] == {
            "namespace": "audioset",
            "id": "/m/04rlf",
            "common_name": None,
        }

    def test_detection_to_dict_omits_intervals_when_absent(self) -> None:
        """When intervals/taxonomy are unset, to_dict() emits None — not [] or {}."""
        detection = Detection(
            event_id="empty_001",
            timestamp=datetime(2025, 12, 5, 12, 0, 0),
            detection_type="species.detected",
        )
        data = detection.to_dict()
        assert data["intervals"] is None
        assert data["taxonomy"] is None

    def test_detection_from_dict_with_intervals(self) -> None:
        """from_dict() should rehydrate intervals from list-of-dicts."""
        data = {
            "event_id": "loc_002",
            "timestamp": "2025-12-05T12:00:00",
            "detection_type": "audio.classified",
            "intervals": [
                {"start_seconds": 1.0, "end_seconds": 2.0, "confidence": 0.7},
                {"start_seconds": 3.0, "end_seconds": 3.5},  # no confidence
            ],
        }
        detection = Detection.from_dict(data)
        assert detection.intervals is not None
        assert len(detection.intervals) == 2
        assert isinstance(detection.intervals[0], TemporalInterval)
        assert detection.intervals[0].start_seconds == 1.0
        assert detection.intervals[0].confidence == 0.7
        assert detection.intervals[1].confidence is None

    def test_detection_from_dict_with_taxonomy(self) -> None:
        """from_dict() should rehydrate taxonomy from a dict."""
        data = {
            "event_id": "tax_002",
            "timestamp": "2025-12-05T12:00:00",
            "detection_type": "audio.classified",
            "taxonomy": {
                "namespace": "audioset",
                "id": "/m/04rlf",
                "common_name": "Music",
            },
        }
        detection = Detection.from_dict(data)
        assert detection.taxonomy is not None
        assert isinstance(detection.taxonomy, TaxonomyRef)
        assert detection.taxonomy.namespace == "audioset"
        assert detection.taxonomy.id == "/m/04rlf"
        assert detection.taxonomy.common_name == "Music"

    def test_detection_from_dict_legacy_payload_without_new_fields(self) -> None:
        """Legacy payloads (no intervals/taxonomy keys) must deserialise."""
        # This is the V1 payload shape from before ADR 0011.
        data = {
            "event_id": "legacy_001",
            "timestamp": "2025-12-05T12:00:00",
            "detection_type": "species.detected",
            "species_code": "amecro",
            "confidence": 0.9,
        }
        detection = Detection.from_dict(data)
        assert detection.intervals is None
        assert detection.taxonomy is None
        assert detection.species_code == "amecro"

    def test_detection_round_trip_with_all_new_fields(self) -> None:
        """to_dict() → from_dict() preserves intervals and taxonomy exactly."""
        original = Detection(
            event_id="rt_001",
            timestamp=datetime(2025, 12, 5, 12, 0, 0, tzinfo=timezone.utc),
            detection_type="audio.classified",
            species_code="audioset_/m/04rlf",
            species_common="Music",
            confidence=0.82,
            audio_clip_path="/data/orpheus/audio/test.flac",
            intervals=[
                TemporalInterval(start_seconds=0.0, end_seconds=2.5, confidence=0.82),
                TemporalInterval(start_seconds=5.0, end_seconds=7.3, confidence=0.71),
            ],
            taxonomy=TaxonomyRef(
                namespace="audioset",
                id="/m/04rlf",
                common_name="Music",
            ),
        )
        rehydrated = Detection.from_dict(original.to_dict())
        assert rehydrated.event_id == original.event_id
        assert rehydrated.detection_type == original.detection_type
        assert rehydrated.species_code == original.species_code
        assert rehydrated.confidence == original.confidence
        assert rehydrated.intervals == original.intervals
        assert rehydrated.taxonomy == original.taxonomy


class TestTemporalInterval:
    """Tests for the TemporalInterval Pydantic model."""

    def test_basic_construction(self) -> None:
        """Construct with start, end, and optional confidence."""
        interval = TemporalInterval(start_seconds=1.5, end_seconds=3.0, confidence=0.9)
        assert interval.start_seconds == 1.5
        assert interval.end_seconds == 3.0
        assert interval.confidence == 0.9

    def test_confidence_optional(self) -> None:
        """confidence defaults to None when not provided."""
        interval = TemporalInterval(start_seconds=0.0, end_seconds=1.0)
        assert interval.confidence is None

    def test_zero_duration_is_allowed(self) -> None:
        """A zero-duration interval is allowed (point-in-time event)."""
        interval = TemporalInterval(start_seconds=1.0, end_seconds=1.0)
        assert interval.start_seconds == interval.end_seconds

    def test_inverted_interval_rejected(self) -> None:
        """end_seconds < start_seconds raises ValidationError.

        Defends downstream consumers from buggy upstream post-processors
        and corrupted roundtrips that would otherwise produce nonsense
        durations.
        """
        import pytest as _pytest  # noqa: PLC0415
        from pydantic import ValidationError  # noqa: PLC0415

        with _pytest.raises(ValidationError, match="must be >="):
            TemporalInterval(start_seconds=2.0, end_seconds=1.0)

    def test_negative_start_rejected(self) -> None:
        """start_seconds < 0 raises ValidationError."""
        import pytest as _pytest  # noqa: PLC0415
        from pydantic import ValidationError  # noqa: PLC0415

        with _pytest.raises(ValidationError, match="must be >= 0"):
            TemporalInterval(start_seconds=-1.0, end_seconds=1.0)

    def test_round_trip_via_model_dump(self) -> None:
        """model_dump → re-construct preserves all fields."""
        original = TemporalInterval(start_seconds=1.0, end_seconds=2.0, confidence=0.5)
        rehydrated = TemporalInterval(**original.model_dump())
        assert rehydrated == original

    def test_equality(self) -> None:
        """Two intervals with the same fields are equal."""
        a = TemporalInterval(start_seconds=1.0, end_seconds=2.0)
        b = TemporalInterval(start_seconds=1.0, end_seconds=2.0)
        assert a == b


class TestTaxonomyRef:
    """Tests for the TaxonomyRef Pydantic model."""

    def test_basic_construction(self) -> None:
        """Construct with namespace and id."""
        ref = TaxonomyRef(namespace="audioset", id="/m/04rlf")
        assert ref.namespace == "audioset"
        assert ref.id == "/m/04rlf"
        assert ref.common_name is None

    def test_with_common_name(self) -> None:
        """common_name is optional but populates when provided."""
        ref = TaxonomyRef(namespace="audioset", id="/m/04rlf", common_name="Music")
        assert ref.common_name == "Music"

    def test_ebird_namespace(self) -> None:
        """Construction with ebird namespace works the same — no enum constraint."""
        ref = TaxonomyRef(namespace="ebird", id="amecro", common_name="American Crow")
        assert ref.namespace == "ebird"
        assert ref.id == "amecro"

    def test_round_trip_via_model_dump(self) -> None:
        """model_dump → re-construct preserves all fields."""
        original = TaxonomyRef(namespace="audioset", id="/m/04rlf", common_name="Music")
        rehydrated = TaxonomyRef(**original.model_dump())
        assert rehydrated == original

    def test_equality(self) -> None:
        """Two refs with the same fields are equal."""
        a = TaxonomyRef(namespace="audioset", id="/m/04rlf")
        b = TaxonomyRef(namespace="audioset", id="/m/04rlf")
        assert a == b


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

    def test_save_and_load_detection_with_intervals(self, db: DetectionDB) -> None:
        """ADR 0011: intervals round-trip through the DB intact."""
        original = Detection(
            event_id="db_intervals_001",
            timestamp=datetime.now(timezone.utc),
            detection_type="audio.classified",
            species_code="audioset_/m/04rlf",
            species_common="Music",
            confidence=0.82,
            intervals=[
                TemporalInterval(start_seconds=0.0, end_seconds=2.5, confidence=0.82),
                TemporalInterval(start_seconds=5.0, end_seconds=7.3, confidence=0.71),
            ],
        )
        db.save(original)
        loaded = db.get_by_event_id("db_intervals_001")
        assert loaded is not None
        assert loaded.intervals is not None
        assert len(loaded.intervals) == 2
        assert loaded.intervals[0].start_seconds == 0.0
        assert loaded.intervals[0].end_seconds == 2.5
        assert loaded.intervals[0].confidence == 0.82
        assert loaded.intervals[1].confidence == 0.71

    def test_save_and_load_detection_with_taxonomy(self, db: DetectionDB) -> None:
        """ADR 0011: taxonomy round-trips through the DB intact."""
        from orpheus_common.detection import TaxonomyRef

        original = Detection(
            event_id="db_taxonomy_001",
            timestamp=datetime.now(timezone.utc),
            detection_type="audio.classified",
            taxonomy=TaxonomyRef(
                namespace="audioset",
                id="/m/04rlf",
                common_name="Music",
            ),
        )
        db.save(original)
        loaded = db.get_by_event_id("db_taxonomy_001")
        assert loaded is not None
        assert loaded.taxonomy is not None
        assert loaded.taxonomy.namespace == "audioset"
        assert loaded.taxonomy.id == "/m/04rlf"
        # common_name is not persisted in discrete columns (namespace+id are
        # the canonical pair); rehydration leaves it as None. That's by design.
        assert loaded.taxonomy.common_name is None

    def test_save_detection_without_intervals_or_taxonomy(self, db: DetectionDB) -> None:
        """Legacy detections (no intervals/taxonomy) save and load cleanly."""
        original = Detection(
            event_id="db_legacy_001",
            timestamp=datetime.now(timezone.utc),
            detection_type="species.detected",
            species_code="amecro",
            confidence=0.9,
        )
        db.save(original)
        loaded = db.get_by_event_id("db_legacy_001")
        assert loaded is not None
        assert loaded.intervals is None
        assert loaded.taxonomy is None

    def test_ensure_schema_updates_is_idempotent(self, tmp_path: Path) -> None:
        """Running ensure_schema_updates on a populated DB is a no-op."""
        from orpheus_common.detection import ensure_schema_updates

        db_path = tmp_path / "idempotent.db"
        db = DetectionDB(db_path=db_path)
        db.save(
            Detection(
                event_id="idem_001",
                timestamp=datetime.now(timezone.utc),
                detection_type="audio.motion",
            )
        )
        # Running the migration again should not crash or duplicate columns.
        ensure_schema_updates(db_path)
        ensure_schema_updates(db_path)
        # Data is still readable.
        loaded = db.get_by_event_id("idem_001")
        assert loaded is not None

    def test_ensure_schema_updates_backfills_entities_covering_index(
        self, tmp_path: Path
    ) -> None:
        """A legacy DB without the Entities-page covering index gains it."""
        from orpheus_common.detection import ensure_schema_updates

        db_path = tmp_path / "legacy_index.db"
        DetectionDB(db_path=db_path)  # fresh schema (includes the index)
        conn = sqlite3.connect(db_path)
        try:
            # Simulate a legacy DB initialised before the index existed.
            conn.execute("DROP INDEX idx_entities_page_covering")
            conn.commit()
            ensure_schema_updates(db_path)
            names = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                )
            }
        finally:
            conn.close()
        assert "idx_entities_page_covering" in names

    def test_query_rows_matches_query(self, db: DetectionDB) -> None:
        """query_rows: same filters/order/limit as query(), raw rows out."""
        for i in range(5):
            db.save(
                Detection(
                    event_id=f"qrows_{i}",
                    timestamp=datetime(2026, 1, 1, 12, i, tzinfo=timezone.utc),
                    detection_type="species.detected" if i % 2 else "audio.motion",
                    species_code=f"sp{i}",
                    confidence=0.5,
                )
            )
        rows = db.query_rows(detection_type="species.detected", limit=2)
        dets = db.query(detection_type="species.detected", limit=2)
        assert [r["event_id"] for r in rows] == [d.event_id for d in dets]
        assert rows[0]["species_code"] == dets[0].species_code
        # Raw row exposes the storage columns (JSON sidecars unparsed).
        assert "metadata" in rows[0].keys()
        assert "event_metadata" in rows[0].keys()

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

    def test_update_entity_replaces_mutable_columns(self, db: DetectionDB) -> None:
        """update_entity folds new state into an existing row by entity_id — the
        additive path late-arrival enrichment needs (save_entity's bare INSERT
        raises on an existing entity_id and its semantics must not change)."""
        original = Entity(
            entity_id="ent_upd_001",
            timestamp=datetime.now(timezone.utc),
            species="amecro",
            common_name="American Crow",
            confidence=0.6,
            evidence=[EntityEvidence(event_id="d1", sensor_id="mic-1", confidence=0.6)],
        )
        db.save_entity(original)

        enriched = Entity(
            entity_id="ent_upd_001",
            timestamp=original.timestamp,
            species="amecro",
            common_name="American Crow",
            confidence=0.93,
            evidence=[
                EntityEvidence(event_id="d1", sensor_id="mic-1", confidence=0.6),
                EntityEvidence(event_id="d2", sensor_id="mic-1", confidence=0.93),
            ],
        )
        assert db.update_entity(enriched) is True

        got = db.get_entity_by_id("ent_upd_001")
        assert got is not None
        assert got.confidence == 0.93
        assert [e.event_id for e in got.evidence] == ["d1", "d2"]

    def test_update_entity_missing_returns_false(self, db: DetectionDB) -> None:
        assert (
            db.update_entity(
                Entity(
                    entity_id="ent_never_saved",
                    timestamp=datetime.now(timezone.utc),
                    species="amecro",
                )
            )
            is False
        )

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

    def test_get_entities_by_common_name(self, db: DetectionDB) -> None:
        """REPRO + fix for the user-reported Entities filter bug:
        the UI dropdown shows COALESCE(common_name, species), so
        users pick the COMMON NAME (e.g. ``"American Robin"``) and
        the filter must match against ``common_name`` as well as the
        slug ``species`` column."""
        db.save_entity(
            Entity(
                entity_id="ent_robin",
                timestamp=datetime.now(timezone.utc),
                species="amerob",
                common_name="American Robin",
            )
        )
        db.save_entity(
            Entity(
                entity_id="ent_crow",
                timestamp=datetime.now(timezone.utc),
                species="amecro",
                common_name="American Crow",
            )
        )

        # Filter by common name (what the dropdown actually sends).
        results = db.get_entities(species="American Robin")
        assert len(results) == 1
        assert results[0].entity_id == "ent_robin"

        # Filter by slug still works (back-compat with code that
        # passes species_code directly, e.g. CrowEntitySection).
        results = db.get_entities(species="amecro")
        assert len(results) == 1
        assert results[0].entity_id == "ent_crow"

    def test_get_entities_exclude_by_common_name(self, db: DetectionDB) -> None:
        """Same symmetry for exclude_species: dropdown values may be
        common names."""
        db.save_entity(
            Entity(
                entity_id="ent_robin",
                timestamp=datetime.now(timezone.utc),
                species="amerob",
                common_name="American Robin",
            )
        )
        db.save_entity(
            Entity(
                entity_id="ent_crow",
                timestamp=datetime.now(timezone.utc),
                species="amecro",
                common_name="American Crow",
            )
        )

        results = db.get_entities(exclude_species="American Robin")
        assert len(results) == 1
        assert results[0].entity_id == "ent_crow"

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


class TestDetectionRootEventId:
    """Tests for Layer 1.5 — root_event_id propagation through the chain.

    The chain spine: every Detection knows the audio.motion event that
    started its source-chain in O(1), without DB lookups. See
    docs/designs/cross-classifier-identity.md §1.1.
    """

    def test_root_event_id_defaults_to_none(self) -> None:
        """Legacy callers that don't pass root_event_id get None — the
        field is optional and back-compatible."""
        det = Detection(
            event_id="legacy_001",
            timestamp=datetime(2025, 12, 5, 12, 0, 0),
            detection_type="species.detected",
        )
        assert det.root_event_id is None

    def test_derive_root_event_id_from_parent_with_root(self) -> None:
        """A parent that already has a root_event_id (one hop deep into
        the chain) — children inherit that root, not the parent's own id."""
        parent = Detection(
            event_id="bird_001",
            timestamp=datetime(2025, 12, 5, 12, 0, 0),
            detection_type="species.detected",
            root_event_id="audio_motion_001",  # parent already knows the root
        )
        assert Detection.derive_root_event_id(parent) == "audio_motion_001"

    def test_derive_root_event_id_from_parent_without_root(self) -> None:
        """A parent with no root_event_id (the parent IS the root, e.g.
        an audio.motion event) — children use the parent's own event_id."""
        parent = Detection(
            event_id="audio_motion_001",
            timestamp=datetime(2025, 12, 5, 12, 0, 0),
            detection_type="audio.motion",
        )
        # Legacy audio.motion event without root set yet (since we set it
        # post-construction in the channel_processor).
        assert Detection.derive_root_event_id(parent) == "audio_motion_001"

    def test_derive_root_event_id_no_parent_returns_none(self) -> None:
        """The root itself has no parent → derive_root_event_id(None) returns None.
        Audio.motion sets its own root_event_id post-construction."""
        assert Detection.derive_root_event_id(None) is None

    def test_chain_traceability_3_hops(self) -> None:
        """Walk: audio.motion → bird → crow. Each step inherits the
        chain root from its immediate parent. The crow.analyzed
        Detection knows the audio.motion event_id in O(1)."""
        audio_motion = Detection(
            event_id="am_001",
            timestamp=datetime(2025, 12, 5, 12, 0, 0),
            detection_type="audio.motion",
        )
        audio_motion.root_event_id = audio_motion.event_id  # audio.motion is its own root

        bird = Detection(
            event_id="bd_001",
            timestamp=datetime(2025, 12, 5, 12, 0, 0),
            detection_type="species.detected",
            source_event_id=audio_motion.event_id,
            root_event_id=Detection.derive_root_event_id(audio_motion),
        )

        crow = Detection(
            event_id="cd_001",
            timestamp=datetime(2025, 12, 5, 12, 0, 0),
            detection_type="crow.analyzed",
            source_event_id=bird.event_id,
            root_event_id=Detection.derive_root_event_id(bird),
        )

        # All three trace back to audio.motion via root_event_id alone.
        assert audio_motion.root_event_id == "am_001"
        assert bird.root_event_id == "am_001"
        assert crow.root_event_id == "am_001"
        # source_event_id remains the immediate parent (the audit chain).
        assert audio_motion.source_event_id is None
        assert bird.source_event_id == "am_001"
        assert crow.source_event_id == "bd_001"

    def test_root_event_id_round_trips_through_dict(self) -> None:
        original = Detection(
            event_id="rt_001",
            timestamp=datetime(2025, 12, 5, 12, 0, 0),
            detection_type="crow.analyzed",
            source_event_id="bd_001",
            root_event_id="am_001",
        )
        rehydrated = Detection.from_dict(original.to_dict())
        assert rehydrated.root_event_id == "am_001"
        assert rehydrated.source_event_id == "bd_001"

    def test_legacy_payload_without_root_event_id_parses(self) -> None:
        """A pre-Layer-1.5 payload (no root_event_id key) parses with
        root_event_id=None — no breakage for in-flight events."""
        data = {
            "event_id": "legacy_002",
            "timestamp": "2025-12-05T12:00:00",
            "detection_type": "species.detected",
            "source_event_id": "am_002",
        }
        det = Detection.from_dict(data)
        assert det.root_event_id is None
        assert det.source_event_id == "am_002"


class TestGetChain:
    """Tests for DetectionDB.get_chain — "metadata appended to metadata"
    view of every Detection sharing a root_event_id."""

    @pytest.fixture
    def db(self, tmp_path: Path) -> DetectionDB:
        return DetectionDB(db_path=tmp_path / "chain.db")

    def test_chain_returns_all_detections_with_same_root(
        self, db: DetectionDB
    ) -> None:
        """Three detections — audio.motion → species.detected → crow.analyzed
        — all with the same root_event_id, return as a chronological list."""
        root = "am-chain-001"
        t0 = datetime(2025, 12, 5, 12, 0, 0, tzinfo=timezone.utc)
        db.save(
            Detection(
                event_id=root,
                timestamp=t0,
                detection_type="audio.motion",
                root_event_id=root,
            )
        )
        db.save(
            Detection(
                event_id="bd-001",
                timestamp=t0 + timedelta(milliseconds=500),
                detection_type="species.detected",
                species_code="corvus",
                source_event_id=root,
                root_event_id=root,
            )
        )
        db.save(
            Detection(
                event_id="cd-001",
                timestamp=t0 + timedelta(seconds=2),
                detection_type="crow.analyzed",
                species_code="crow",
                source_event_id="bd-001",
                root_event_id=root,
            )
        )

        chain = db.get_chain(root)
        assert len(chain) == 3
        # Chronological order.
        assert chain[0].event_id == root
        assert chain[1].event_id == "bd-001"
        assert chain[2].event_id == "cd-001"
        # Detection types tell the story of the chain.
        types = [d.detection_type for d in chain]
        assert types == ["audio.motion", "species.detected", "crow.analyzed"]

    def test_chain_does_not_leak_other_events(self, db: DetectionDB) -> None:
        """A different root_event_id's detections must not appear in our
        chain query — even if the timestamps are close."""
        ts = datetime(2025, 12, 5, 12, 0, 0, tzinfo=timezone.utc)
        # Our chain.
        db.save(
            Detection(
                event_id="bd-ours",
                timestamp=ts,
                detection_type="species.detected",
                root_event_id="am-target",
            )
        )
        # Unrelated chain at the same moment.
        db.save(
            Detection(
                event_id="bd-other",
                timestamp=ts,
                detection_type="species.detected",
                root_event_id="am-different",
            )
        )

        chain = db.get_chain("am-target")
        assert len(chain) == 1
        assert chain[0].event_id == "bd-ours"

    def test_chain_returns_empty_when_no_match(self, db: DetectionDB) -> None:
        """Unknown root_event_id → empty list, not an error."""
        chain = db.get_chain("nope-doesnt-exist")
        assert chain == []

    def test_chain_includes_multi_classifier_evidence(
        self, db: DetectionDB
    ) -> None:
        """The chain captures evidence from EVERY classifier that processed
        the same audio.motion event — bird-detection AND audio-events AND
        crow-detection all show up together."""
        root = "am-multi-classifier"
        t0 = datetime(2025, 12, 5, 12, 0, 0, tzinfo=timezone.utc)
        # audio.motion root
        db.save(
            Detection(
                event_id=root,
                timestamp=t0,
                detection_type="audio.motion",
                root_event_id=root,
            )
        )
        # bird-detection
        db.save(
            Detection(
                event_id="bd-1",
                timestamp=t0 + timedelta(milliseconds=200),
                detection_type="species.detected",
                species_code="corvus",
                source_event_id=root,
                root_event_id=root,
            )
        )
        # audio-events (parallel classifier on the same audio.motion clip)
        db.save(
            Detection(
                event_id="ae-1",
                timestamp=t0 + timedelta(milliseconds=350),
                detection_type="audio.classified",
                species_code="audioset_/m/04s8yn",
                source_event_id=root,
                root_event_id=root,
            )
        )
        # crow-tools (downstream of bird-detection)
        db.save(
            Detection(
                event_id="cd-1",
                timestamp=t0 + timedelta(milliseconds=1500),
                detection_type="crow.analyzed",
                species_code="crow",
                source_event_id="bd-1",
                root_event_id=root,
            )
        )

        chain = db.get_chain(root)
        # All four detections are linked back to the same root.
        assert len(chain) == 4
        types = {d.detection_type for d in chain}
        assert types == {
            "audio.motion",
            "species.detected",
            "audio.classified",
            "crow.analyzed",
        }


class TestEntityLayer2:
    """Tests for Layer 2 schema additions: event_signature on Entity and
    per-evidence (species_code / species_common / taxonomy / detection_type)
    fields on EntityEvidence."""

    @pytest.fixture
    def db(self, tmp_path: Path) -> DetectionDB:
        return DetectionDB(db_path=tmp_path / "layer2.db")

    def test_event_signature_round_trips_through_db(self, db: DetectionDB) -> None:
        """A saved Entity with an event_signature dict reads back identical."""
        sig = {
            "audio_motion_source_ids": ["am-001", "am-002"],
            "sensor_ids": ["mic-1", "mic-2"],
            "start_time": "2026-05-21T20:00:00+00:00",
            "end_time": "2026-05-21T20:00:02.500000+00:00",
        }
        entity = Entity(
            entity_id="layer2_sig_001",
            timestamp=datetime.now(timezone.utc),
            species="amecro",
            common_name="American Crow",
            confidence=0.9,
            evidence=[EntityEvidence(event_id="d1", sensor_id="mic-1", confidence=0.9)],
            event_signature=sig,
        )
        db.save_entity(entity)
        loaded = db.get_entities()
        match = next(e for e in loaded if e.entity_id == "layer2_sig_001")
        assert match.event_signature == sig

    def test_legacy_entity_has_event_signature_none(self, db: DetectionDB) -> None:
        """An Entity saved without event_signature reads back with None."""
        entity = Entity(
            entity_id="layer2_legacy_001",
            timestamp=datetime.now(timezone.utc),
            species="amerob",
            evidence=[],
        )
        db.save_entity(entity)
        loaded = db.get_entities()
        match = next(e for e in loaded if e.entity_id == "layer2_legacy_001")
        assert match.event_signature is None

    def test_per_evidence_taxonomy_round_trips(self, db: DetectionDB) -> None:
        """Each EntityEvidence carries its own taxonomy + species_code."""
        from orpheus_common.detection import TaxonomyRef

        ev1 = EntityEvidence(
            event_id="bird-1",
            sensor_id="mic-1",
            confidence=0.9,
            species_code="corvus",
            species_common="American Crow",
            taxonomy=TaxonomyRef(
                namespace="ioc", id="Corvus brachyrhynchos", common_name="American Crow"
            ),
            detection_type="species.detected",
        )
        ev2 = EntityEvidence(
            event_id="audio-1",
            sensor_id="mic-1",
            confidence=0.85,
            species_code="audioset_/m/04s8yn",
            species_common="Crow",
            taxonomy=TaxonomyRef(namespace="audioset", id="/m/04s8yn"),
            detection_type="audio.classified",
        )
        entity = Entity(
            entity_id="layer2_evidence_001",
            timestamp=datetime.now(timezone.utc),
            species="corvus",
            evidence=[ev1, ev2],
        )
        db.save_entity(entity)
        loaded = db.get_entities()
        match = next(e for e in loaded if e.entity_id == "layer2_evidence_001")
        assert len(match.evidence) == 2

        # Multi-classifier evidence preserved with distinct taxonomy refs.
        evs_by_type = {ev.detection_type: ev for ev in match.evidence}
        assert evs_by_type["species.detected"].taxonomy.namespace == "ioc"
        assert (
            evs_by_type["species.detected"].taxonomy.id
            == "Corvus brachyrhynchos"
        )
        assert evs_by_type["audio.classified"].taxonomy.namespace == "audioset"
        assert evs_by_type["audio.classified"].taxonomy.id == "/m/04s8yn"
        # species_code preserved per-evidence (legacy classifiers' native codes).
        assert evs_by_type["species.detected"].species_code == "corvus"
        assert evs_by_type["audio.classified"].species_code == "audioset_/m/04s8yn"

    def test_evidence_with_no_taxonomy_round_trips(self, db: DetectionDB) -> None:
        """Crow-tools-style evidence (no taxonomy) loads back as None."""
        ev = EntityEvidence(
            event_id="crow-1",
            sensor_id="mic-1",
            confidence=0.8,
            species_code="crow",
            species_common="Crow",
            taxonomy=None,
            detection_type="crow.analyzed",
        )
        entity = Entity(
            entity_id="layer2_no_tax_001",
            timestamp=datetime.now(timezone.utc),
            species="crow",
            evidence=[ev],
        )
        db.save_entity(entity)
        loaded = db.get_entities()
        match = next(e for e in loaded if e.entity_id == "layer2_no_tax_001")
        assert match.evidence[0].taxonomy is None
        assert match.evidence[0].detection_type == "crow.analyzed"


class TestQueryBoundHelpers:
    """The shared ISO-bound helpers every query path now uses (consolidates the
    count_by_hour / species_distribution undercount, which formerly skipped the
    UTC-normalization + microsecond truncation that query() applied)."""

    def test_lower_bound_treats_naive_as_utc_and_truncates_microseconds(self) -> None:
        naive = datetime(2026, 1, 2, 3, 4, 5, 123456)
        assert _iso_lower_bound(naive) == "2026-01-02T03:04:05+00:00"

    def test_upper_bound_pushes_to_end_of_second(self) -> None:
        naive = datetime(2026, 1, 2, 3, 4, 5, 1)
        assert _iso_upper_bound(naive) == "2026-01-02T03:04:05.999999+00:00"

    def test_bounds_convert_aware_offset_to_utc(self) -> None:
        # 03:04 at +05:00 is 22:04 the previous day in UTC.
        aware = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone(timedelta(hours=5)))
        assert _iso_lower_bound(aware) == "2026-01-01T22:04:05+00:00"
        assert _iso_upper_bound(aware) == "2026-01-01T22:04:05.999999+00:00"

    def test_lower_bound_below_an_untruncated_same_second_row(self) -> None:
        # The whole point of truncating: a row anywhere in the boundary second
        # must sort >= the lower bound. A naive bound carrying live microseconds
        # would exclude rows earlier in that second (the historical undercount).
        bound = _iso_lower_bound(datetime(2026, 1, 2, 3, 4, 5, 900000))
        early_in_second = datetime(2026, 1, 2, 3, 4, 5, 1, tzinfo=timezone.utc).isoformat()
        assert early_in_second >= bound


class TestReadFailSoft:
    """A single malformed persisted blob must not 500 an entire read."""

    @pytest.fixture
    def db(self, tmp_path: Path) -> DetectionDB:
        return DetectionDB(db_path=tmp_path / "test.db")

    def test_safe_model_returns_none_on_bad_row(self) -> None:
        good = _safe_model(EntityEvidence, {"event_id": "d1", "confidence": 0.5})
        assert isinstance(good, EntityEvidence)
        assert good.event_id == "d1"
        # confidence can't coerce -> ValidationError -> None, not a raise.
        assert _safe_model(EntityEvidence, {"event_id": "d2", "confidence": "nope"}) is None

    def test_get_entities_skips_malformed_evidence(self, db: DetectionDB) -> None:
        entity = Entity(
            entity_id="ent_mixed_evidence",
            timestamp=datetime.now(timezone.utc),
            species="amecro",
            evidence=[EntityEvidence(event_id="good", sensor_id="mic-1", confidence=0.9)],
        )
        db.save_entity(entity)

        # Corrupt the persisted evidence: one valid object + one unparseable.
        raw = sqlite3.connect(db.db_path)
        try:
            raw.execute(
                "UPDATE entities SET evidence = ? WHERE entity_id = ?",
                (
                    json.dumps(
                        [
                            {"event_id": "good", "sensor_id": "mic-1", "confidence": 0.9},
                            {"event_id": "bad", "confidence": "not-a-float"},
                        ]
                    ),
                    "ent_mixed_evidence",
                ),
            )
            raw.commit()
        finally:
            raw.close()

        # Read must succeed, dropping only the bad evidence object.
        results = db.get_entities()
        match = next(e for e in results if e.entity_id == "ent_mixed_evidence")
        assert len(match.evidence) == 1
        assert match.evidence[0].event_id == "good"


class TestIterQuery:
    """The streaming query primitive — a drop-in for query() (same filters +
    newest-first order) that yields one Detection at a time so bulk consumers
    (auto-discovery, replay) don't materialise the whole window and OOM."""

    @pytest.fixture
    def db(self, tmp_path: Path) -> DetectionDB:
        return DetectionDB(db_path=tmp_path / "test.db")

    def _seed(self, db: DetectionDB, n: int) -> None:
        base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        for i in range(n):
            db.save(
                Detection(
                    event_id=f"e{i:03d}",
                    timestamp=base + timedelta(minutes=i),
                    detection_type="species.detected" if i % 2 == 0 else "audio.motion",
                    species_code="amecro",
                    confidence=0.5 + (i % 5) / 10.0,
                )
            )

    def test_iter_matches_query_rows_and_order(self, db: DetectionDB) -> None:
        self._seed(db, 25)
        streamed = [d.event_id for d in db.iter_query()]
        queried = [d.event_id for d in db.query(limit=10_000)]
        assert streamed == queried  # identical rows, identical DESC order
        assert len(streamed) == 25

    def test_batch_size_does_not_change_results(self, db: DetectionDB) -> None:
        self._seed(db, 25)
        one_at_a_time = [d.event_id for d in db.iter_query(batch_size=1)]
        big_batches = [d.event_id for d in db.iter_query(batch_size=1000)]
        assert one_at_a_time == big_batches
        assert len(one_at_a_time) == 25

    def test_filters_apply_like_query(self, db: DetectionDB) -> None:
        self._seed(db, 20)
        streamed = [d.event_id for d in db.iter_query(detection_type="species.detected")]
        queried = [
            d.event_id for d in db.query(detection_type="species.detected", limit=10_000)
        ]
        assert streamed == queried
        assert len(streamed) == 10  # even-indexed rows only

    def test_time_range_is_inclusive(self, db: DetectionDB) -> None:
        self._seed(db, 20)  # minutes 0..19 from base
        base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        rows = list(
            db.iter_query(
                start_time=base + timedelta(minutes=5),
                end_time=base + timedelta(minutes=9),
            )
        )
        assert len(rows) == 5  # minutes 5,6,7,8,9 inclusive

    def test_empty_result_is_empty_iterator(self, db: DetectionDB) -> None:
        assert list(db.iter_query()) == []
        self._seed(db, 3)
        assert list(db.iter_query(species_code="nonexistent")) == []


class TestEntitySelfGenerated:
    """Corollary-discharge `is_self_generated` field: additive, round-trips
    through model + DB, and legacy rows / DBs default it to False."""

    @pytest.fixture
    def db(self, tmp_path: Path) -> DetectionDB:
        return DetectionDB(db_path=tmp_path / "test.db")

    def test_defaults_false_and_serializes(self) -> None:
        e = Entity(entity_id="x", timestamp=datetime.now(timezone.utc), species="amecro")
        assert e.is_self_generated is False
        assert e.to_dict()["is_self_generated"] is False

    def test_from_entity_event_reads_flag(self) -> None:
        base = {
            "entity_id": "x",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "species_code": "amecro",
        }
        assert Entity.from_entity_event({**base, "is_self_generated": True}).is_self_generated
        # Absent key → False (legacy EntityEvent dicts).
        assert Entity.from_entity_event(base).is_self_generated is False

    def test_persists_and_reads_back(self, db: DetectionDB) -> None:
        now = datetime.now(timezone.utc)
        db.save_entity(Entity(entity_id="sg1", timestamp=now, species="amecro",
                              is_self_generated=True))
        db.save_entity(Entity(entity_id="sg0", timestamp=now, species="amecro",
                              is_self_generated=False))
        by_id = {e.entity_id: e for e in db.get_entities()}
        assert by_id["sg1"].is_self_generated is True
        assert by_id["sg0"].is_self_generated is False

    def test_legacy_db_migrates_and_defaults_false(self, tmp_path: Path) -> None:
        # An entities table predating both event_signature AND is_self_generated.
        path = tmp_path / "legacy.db"
        raw = sqlite3.connect(path)
        try:
            raw.execute(
                "CREATE TABLE entities ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, entity_id TEXT UNIQUE NOT NULL, "
                "timestamp TEXT NOT NULL, species TEXT NOT NULL, common_name TEXT, "
                "confidence REAL, evidence TEXT, context TEXT)"
            )
            raw.execute(
                "INSERT INTO entities (entity_id, timestamp, species) VALUES (?, ?, ?)",
                ("legacy1", datetime.now(timezone.utc).isoformat(), "amecro"),
            )
            raw.commit()
        finally:
            raw.close()
        # Constructing DetectionDB runs ensure_schema_updates → adds the column.
        db = DetectionDB(db_path=path)
        match = next(e for e in db.get_entities() if e.entity_id == "legacy1")
        assert match.is_self_generated is False
        # And new saves on the migrated DB carry the flag.
        db.save_entity(Entity(entity_id="new1", timestamp=datetime.now(timezone.utc),
                              species="amecro", is_self_generated=True))
        match2 = next(e for e in db.get_entities() if e.entity_id == "new1")
        assert match2.is_self_generated is True


class TestEntityTypeColumn:
    """Additive entity_type column ([ARCH]): round-trips through model + DB,
    legacy rows/DBs default to None."""

    @pytest.fixture
    def db(self, tmp_path: Path) -> DetectionDB:
        return DetectionDB(db_path=tmp_path / "test.db")

    def test_model_round_trips(self) -> None:
        e = Entity(entity_id="x", timestamp=datetime.now(timezone.utc), species="amecro",
                   entity_type="Animal.Bird")
        assert e.to_dict()["entity_type"] == "Animal.Bird"
        ev = {
            "entity_id": "x",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "species_code": "amecro",
            "entity_type": "Animal.Bird.Crow",
        }
        assert Entity.from_entity_event(ev).entity_type == "Animal.Bird.Crow"
        # Absent → None (legacy EntityEvent dicts).
        ev.pop("entity_type")
        assert Entity.from_entity_event(ev).entity_type is None

    def test_persists_and_reads_back(self, db: DetectionDB) -> None:
        now = datetime.now(timezone.utc)
        db.save_entity(Entity(entity_id="et1", timestamp=now, species="amecro",
                              entity_type="Animal.Bird.Crow"))
        db.save_entity(Entity(entity_id="et0", timestamp=now, species="amecro"))
        by_id = {e.entity_id: e for e in db.get_entities()}
        assert by_id["et1"].entity_type == "Animal.Bird.Crow"
        assert by_id["et0"].entity_type is None

    def test_legacy_db_migrates_and_defaults_none(self, tmp_path: Path) -> None:
        path = tmp_path / "legacy.db"
        raw = sqlite3.connect(path)
        try:
            raw.execute(
                "CREATE TABLE entities ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, entity_id TEXT UNIQUE NOT NULL, "
                "timestamp TEXT NOT NULL, species TEXT NOT NULL, common_name TEXT, "
                "confidence REAL, evidence TEXT, context TEXT)"
            )
            raw.execute(
                "INSERT INTO entities (entity_id, timestamp, species) VALUES (?, ?, ?)",
                ("legacy1", datetime.now(timezone.utc).isoformat(), "amecro"),
            )
            raw.commit()
        finally:
            raw.close()
        db = DetectionDB(db_path=path)  # ensure_schema_updates adds the column
        assert next(e for e in db.get_entities() if e.entity_id == "legacy1").entity_type is None
        db.save_entity(Entity(entity_id="new1", timestamp=datetime.now(timezone.utc),
                              species="amecro", entity_type="Animal.Bird.Crow"))
        assert next(
            e for e in db.get_entities() if e.entity_id == "new1"
        ).entity_type == "Animal.Bird.Crow"


class TestStatementTimeout:
    """Portal prerequisite N2: a per-query wall-time budget so a runaway
    portal/LLM query is interrupted instead of starving the box."""

    def test_slow_query_is_interrupted(self, tmp_path: Path) -> None:
        import sqlite3

        from orpheus_common.detection.database import open_connection

        conn = open_connection(tmp_path / "t.db", statement_timeout_seconds=0.05)
        try:
            with pytest.raises(sqlite3.OperationalError, match="interrupt"):
                # A deliberately expensive recursive scan (~hundreds of ms).
                conn.execute(
                    "WITH RECURSIVE c(x) AS "
                    "(SELECT 1 UNION ALL SELECT x+1 FROM c WHERE x < 3000000) "
                    "SELECT count(*) FROM c"
                ).fetchone()
        finally:
            conn.close()

    def test_no_timeout_by_default(self, tmp_path: Path) -> None:
        from orpheus_common.detection.database import open_connection

        conn = open_connection(tmp_path / "t.db")
        try:
            row = conn.execute(
                "WITH RECURSIVE c(x) AS "
                "(SELECT 1 UNION ALL SELECT x+1 FROM c WHERE x < 200000) "
                "SELECT count(*) FROM c"
            ).fetchone()
            assert row[0] == 200000
        finally:
            conn.close()

    def test_detection_db_threads_the_budget(self, tmp_path: Path) -> None:
        db = DetectionDB(db_path=tmp_path / "d.db", statement_timeout_seconds=5.0)
        assert db.statement_timeout_seconds == 5.0
        # A normal query well under the budget works untouched.
        assert db.query(limit=5) == []

    def test_iter_query_bypasses_the_per_query_budget(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        # The budget is per-QUERY (connection-per-call); iter_query's connection
        # lives for the whole stream, so inheriting it would abort any long drain
        # mid-iteration — the exact caveat in _install_statement_timeout's
        # contract. iter_query must open its connection with NO budget.
        from orpheus_common.detection import database as db_mod

        db = DetectionDB(db_path=tmp_path / "d.db", statement_timeout_seconds=5.0)
        db.save(
            Detection(
                event_id="e1",
                timestamp=datetime.now(timezone.utc),
                detection_type="audio.motion",
            )
        )
        installed: list = []
        real = db_mod._install_statement_timeout

        def spy(conn, timeout_seconds):
            installed.append(timeout_seconds)
            real(conn, timeout_seconds)

        monkeypatch.setattr(db_mod, "_install_statement_timeout", spy)
        assert db.query(limit=5)  # per-call path: budget applies
        assert installed[-1] == 5.0
        installed.clear()
        assert [d.event_id for d in db.iter_query()] == ["e1"]  # streaming path
        assert installed == [None]  # no budget on the stream's connection

    def test_iter_query_still_honors_read_only(self, tmp_path: Path) -> None:
        # Bypassing the budget must NOT bypass read-only: the replica-facing
        # stream still opens mode=ro.
        writer = DetectionDB(db_path=tmp_path / "d.db")
        writer.save(
            Detection(
                event_id="e1",
                timestamp=datetime.now(timezone.utc),
                detection_type="audio.motion",
            )
        )
        ro = DetectionDB(
            db_path=tmp_path / "d.db", read_only=True, statement_timeout_seconds=5.0
        )
        assert [d.event_id for d in ro.iter_query()] == ["e1"]
