"""Tests for the root_event_id backfill helper."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from orpheus_common.detection import (
    Detection,
    DetectionDB,
    backfill_root_event_ids,
)


@pytest.fixture
def db(tmp_path: Path) -> DetectionDB:
    return DetectionDB(db_path=tmp_path / "backfill.db")


def _insert_legacy(
    db: DetectionDB,
    *,
    event_id: str,
    detection_type: str,
    source_event_id: str | None = None,
    timestamp: datetime | None = None,
) -> None:
    """Insert a detection WITHOUT root_event_id (legacy state)."""
    ts = timestamp or datetime.now(timezone.utc)
    det = Detection(
        event_id=event_id,
        timestamp=ts,
        detection_type=detection_type,
        source_event_id=source_event_id,
        # root_event_id deliberately omitted — simulating legacy data.
    )
    db.save(det)


class TestBackfillChainWalking:
    def test_simple_chain_backfilled(self, db: DetectionDB) -> None:
        """audio.motion -> species.detected — legacy row gets root populated."""
        _insert_legacy(db, event_id="am-1", detection_type="audio.motion")
        _insert_legacy(
            db,
            event_id="bd-1",
            detection_type="species.detected",
            source_event_id="am-1",
        )

        stats = backfill_root_event_ids(db)
        assert stats["scanned"] == 2
        assert stats["updated"] == 2

        # Both rows now reference the audio.motion as their root.
        loaded = db.get_chain("am-1")
        assert len(loaded) == 2
        assert all(d.root_event_id == "am-1" for d in loaded)

    def test_two_hop_chain_walks_correctly(self, db: DetectionDB) -> None:
        """audio.motion -> bird-detection -> crow-detection.

        Crow's source is bird, but the root is the audio.motion.
        """
        _insert_legacy(db, event_id="am-1", detection_type="audio.motion")
        _insert_legacy(
            db, event_id="bd-1", detection_type="species.detected",
            source_event_id="am-1",
        )
        _insert_legacy(
            db, event_id="cd-1", detection_type="crow.analyzed",
            source_event_id="bd-1",
        )

        backfill_root_event_ids(db)

        chain = db.get_chain("am-1")
        assert len(chain) == 3  # all 3 traced back to am-1
        types = {d.detection_type for d in chain}
        assert types == {"audio.motion", "species.detected", "crow.analyzed"}

    def test_audio_motion_self_root(self, db: DetectionDB) -> None:
        """An audio.motion without source_event_id is its own root."""
        _insert_legacy(db, event_id="am-only", detection_type="audio.motion")
        backfill_root_event_ids(db)
        loaded = db.get_chain("am-only")
        assert len(loaded) == 1
        assert loaded[0].root_event_id == "am-only"

    def test_broken_chain_skipped(self, db: DetectionDB) -> None:
        """A detection whose source_event_id references a missing event
        is skipped — we can't determine its root."""
        _insert_legacy(
            db, event_id="orphan", detection_type="species.detected",
            source_event_id="does-not-exist",
        )

        stats = backfill_root_event_ids(db)
        assert stats["scanned"] == 1
        assert stats["updated"] == 0
        assert stats["skipped_chain_broken"] == 1
        loaded = db.get_by_event_id("orphan")
        assert loaded is not None
        assert loaded.root_event_id is None

    def test_already_populated_rows_skipped(self, db: DetectionDB) -> None:
        """Rows already with root_event_id are not scanned (idempotent)."""
        # Manually set root_event_id (mimicking a non-legacy row).
        ts = datetime.now(timezone.utc)
        db.save(
            Detection(
                event_id="already-rooted",
                timestamp=ts,
                detection_type="species.detected",
                source_event_id="am-known",
                root_event_id="am-known",
            )
        )
        # Plus a legacy row that needs backfilling.
        _insert_legacy(db, event_id="am-known", detection_type="audio.motion")
        _insert_legacy(
            db, event_id="legacy", detection_type="species.detected",
            source_event_id="am-known",
        )

        stats = backfill_root_event_ids(db)
        # scanned reflects only NULL-root rows: am-known + legacy = 2.
        assert stats["scanned"] == 2
        assert stats["updated"] == 2
        # The pre-rooted row stays unchanged.
        assert db.get_by_event_id("already-rooted").root_event_id == "am-known"


class TestBackfillBrokenChainsTerminate:
    """Regression: when broken-chain rows exceed batch_size, the
    backfill must NOT infinite-loop. The fix uses an offset that
    advances past broken rows so the next batch picks up new rows
    instead of re-fetching the same ones."""

    def test_broken_chains_exceed_batch_size_still_terminates(
        self, db: DetectionDB
    ) -> None:
        # 50 broken rows + 10 good ones, with batch_size=20 to force
        # multiple batches of all-broken rows before reaching any
        # resolvable rows.
        for i in range(50):
            _insert_legacy(
                db, event_id=f"broken-{i:03d}",
                detection_type="species.detected",
                source_event_id="does-not-exist",
            )
        _insert_legacy(db, event_id="am-1", detection_type="audio.motion")
        for i in range(10):
            _insert_legacy(
                db, event_id=f"good-{i:03d}",
                detection_type="species.detected",
                source_event_id="am-1",
            )

        stats = backfill_root_event_ids(db, batch_size=20)
        # All 61 rows scanned; 11 (am-1 + 10 good) resolved; 50 broken.
        assert stats["scanned"] == 61
        assert stats["updated"] == 11
        assert stats["skipped_chain_broken"] == 50

    def test_all_broken_doesnt_loop_forever(self, db: DetectionDB) -> None:
        """Pathological: every row in the DB has a broken chain. With
        the old code this would infinite-loop on each batch's
        all-broken result. New code advances the offset past them."""
        for i in range(15):
            _insert_legacy(
                db, event_id=f"broken-{i:03d}",
                detection_type="species.detected",
                source_event_id="missing",
            )

        stats = backfill_root_event_ids(db, batch_size=5)
        assert stats["scanned"] == 15
        assert stats["updated"] == 0
        assert stats["skipped_chain_broken"] == 15


class TestDryRun:
    def test_dry_run_doesnt_write(self, db: DetectionDB) -> None:
        _insert_legacy(db, event_id="am-1", detection_type="audio.motion")
        _insert_legacy(
            db, event_id="bd-1", detection_type="species.detected",
            source_event_id="am-1",
        )

        stats = backfill_root_event_ids(db, dry_run=True)
        assert stats["scanned"] == 2
        assert stats["updated"] == 2  # would-have-updated count
        assert stats["dry_run"] is True

        # But the DB is unchanged.
        bd = db.get_by_event_id("bd-1")
        assert bd is not None
        assert bd.root_event_id is None


class TestIdempotent:
    def test_running_twice_is_a_no_op(self, db: DetectionDB) -> None:
        _insert_legacy(db, event_id="am-1", detection_type="audio.motion")
        _insert_legacy(
            db, event_id="bd-1", detection_type="species.detected",
            source_event_id="am-1",
        )
        first = backfill_root_event_ids(db)
        second = backfill_root_event_ids(db)
        assert first["updated"] == 2
        assert second["scanned"] == 0
        assert second["updated"] == 0
