"""Tests for the entity_type migration ([ARCH])."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from orpheus_common.detection import DetectionDB, Entity, EntityEvidence, TaxonomyRef
from orpheus_common.detection.entity_type_backfill import backfill_entity_types


def _legacy_entity(eid, taxonomy, species_code, detection_type, confidence=0.9) -> Entity:
    """An entity with entity_type unset (NULL) — a pre-feature row."""
    return Entity(
        entity_id=eid,
        timestamp=datetime.now(timezone.utc),
        species=species_code,
        evidence=[
            EntityEvidence(
                event_id="d-" + eid,
                species_code=species_code,
                confidence=confidence,
                taxonomy=taxonomy,
                detection_type=detection_type,
            )
        ],
        entity_type=None,
    )


class TestEntityTypeBackfill:
    @pytest.fixture
    def db(self, tmp_path: Path) -> DetectionDB:
        return DetectionDB(db_path=tmp_path / "test.db")

    def test_derives_and_is_idempotent(self, db: DetectionDB) -> None:
        db.save_entity(
            _legacy_entity(
                "c1", TaxonomyRef(namespace="ioc", id="Corvus brachyrhynchos"),
                "corvus", "species.detected",
            )
        )
        # Unresolvable: no taxonomy, ambiguous detection_type, unknown code.
        db.save_entity(_legacy_entity("u1", None, "unknownx", "audio.classified"))

        result = backfill_entity_types(db)
        assert result["updated"] == 1
        assert result["skipped_unresolved"] == 1

        by_id = {e.entity_id: e for e in db.get_entities()}
        assert by_id["c1"].entity_type == "Animal.Bird.Crow"
        assert by_id["u1"].entity_type is None

        # Idempotent: a second run makes no new updates (c1 now non-NULL).
        assert backfill_entity_types(db)["updated"] == 0

    def test_dry_run_does_not_write(self, db: DetectionDB) -> None:
        db.save_entity(
            _legacy_entity(
                "c1", TaxonomyRef(namespace="ioc", id="Corvus brachyrhynchos"),
                "corvus", "species.detected",
            )
        )
        result = backfill_entity_types(db, dry_run=True)
        assert result["dry_run"] is True
        assert result["updated"] == 1  # WOULD update one
        # ...but nothing was written.
        assert next(e for e in db.get_entities() if e.entity_id == "c1").entity_type is None

    def test_dry_run_streams_in_batches_and_counts_match_real_run(
        self, db: DetectionDB
    ) -> None:
        # Dry-run rides the same rowid-paged loop as the real run (the old
        # fetchall branch materialised every NULL row's evidence — the OOM
        # pattern this module exists to avoid). With batch_size smaller than
        # the table, pagination must still scan every row exactly once even
        # though nothing leaves the IS-NULL set in a dry run.
        for i in range(5):
            db.save_entity(
                _legacy_entity(
                    f"c{i}", TaxonomyRef(namespace="ioc", id="Corvus brachyrhynchos"),
                    "corvus", "species.detected",
                )
            )
            db.save_entity(_legacy_entity(f"u{i}", None, "unknownx", "audio.classified"))

        dry = backfill_entity_types(db, batch_size=3, dry_run=True)
        assert dry == {
            "scanned": 10,
            "updated": 5,
            "skipped_unresolved": 5,
            "dry_run": True,
        }
        # Nothing written.
        assert all(e.entity_type is None for e in db.get_entities())
        # The real run agrees with the dry-run's forecast.
        real = backfill_entity_types(db, batch_size=3)
        assert (real["scanned"], real["updated"], real["skipped_unresolved"]) == (10, 5, 5)

    def test_only_touches_null_rows(self, db: DetectionDB) -> None:
        # An entity that already has an entity_type is left alone.
        db.save_entity(
            Entity(
                entity_id="pre",
                timestamp=datetime.now(timezone.utc),
                species="amecro",
                entity_type="Animal.Bird",  # pre-set, e.g. by live emission
            )
        )
        result = backfill_entity_types(db)
        assert result["scanned"] == 0  # the WHERE entity_type IS NULL set is empty
        assert next(e for e in db.get_entities() if e.entity_id == "pre").entity_type == (
            "Animal.Bird"
        )
