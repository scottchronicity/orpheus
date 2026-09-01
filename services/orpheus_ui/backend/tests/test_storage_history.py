"""Tests for daily storage history + fill-rate projection."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import orpheus_ui.storage_history as storage_history_mod
from orpheus_ui.storage_history import (
    StorageHistoryDB,
    compute_rate_and_projection,
    get_storage_history_db,
)

GB = 1024**3

_FAKE_VOLUMES = [
    {
        "key": "system", "label": "System", "path": "/",
        "total": 100 * GB, "used": 40 * GB, "free": 60 * GB,
        "percent": 40.0, "ok": True, "error": None,
    },
    {
        "key": "orpheus", "label": "Orpheus Data", "path": "/data/orpheus",
        "total": 500 * GB, "used": 450 * GB, "free": 50 * GB,
        "percent": 90.0, "ok": True, "error": None,
    },
]


class TestRateAndProjection:
    def test_steady_fill_projects_days_until_full(self) -> None:
        series = [
            {"day": "2026-06-01", "free_bytes": 100 * GB},
            {"day": "2026-06-02", "free_bytes": 99 * GB},
            {"day": "2026-06-03", "free_bytes": 98 * GB},
            {"day": "2026-06-04", "free_bytes": 97 * GB},
        ]
        r = compute_rate_and_projection(series, current_free=97 * GB)
        assert round(r["free_bytes_per_day"] / GB, 3) == -1.0  # shrinking 1 GB/day
        assert r["projected_days_until_full"] == 97.0

    def test_flat_usage_has_no_projection(self) -> None:
        series = [
            {"day": "2026-06-01", "free_bytes": 50 * GB},
            {"day": "2026-06-02", "free_bytes": 50 * GB},
        ]
        r = compute_rate_and_projection(series, 50 * GB)
        assert r["free_bytes_per_day"] == 0.0
        assert r["projected_days_until_full"] is None

    def test_growing_free_space_has_no_projection(self) -> None:
        series = [
            {"day": "2026-06-01", "free_bytes": 40 * GB},
            {"day": "2026-06-02", "free_bytes": 45 * GB},
        ]
        r = compute_rate_and_projection(series, 45 * GB)
        assert r["free_bytes_per_day"] > 0
        assert r["projected_days_until_full"] is None

    def test_single_point_is_insufficient(self) -> None:
        r = compute_rate_and_projection(
            [{"day": "2026-06-01", "free_bytes": 50 * GB}], 50 * GB
        )
        assert r["free_bytes_per_day"] is None
        assert r["projected_days_until_full"] is None

    def test_handles_gaps_in_days(self) -> None:
        # A 3-day gap: 90 -> 60 over 3 days = -10 GB/day.
        series = [
            {"day": "2026-06-01", "free_bytes": 90 * GB},
            {"day": "2026-06-04", "free_bytes": 60 * GB},
        ]
        r = compute_rate_and_projection(series, 60 * GB)
        assert round(r["free_bytes_per_day"] / GB, 3) == -10.0
        assert r["projected_days_until_full"] == 6.0


class TestStorageHistoryDB:
    def test_sample_is_idempotent_per_day(self, tmp_path: Path) -> None:
        db = StorageHistoryDB(db_path=tmp_path / "orpheus.db")
        with patch(
            "orpheus_ui.storage_history.list_storage_volumes",
            return_value=_FAKE_VOLUMES,
        ):
            db.sample_now(day="2026-06-03")
            db.sample_now(day="2026-06-04")
            db.sample_now(day="2026-06-04")  # same day again
        hist = db.history("orpheus", days=30)
        assert [h["day"] for h in hist] == ["2026-06-03", "2026-06-04"]
        assert hist[-1]["free_bytes"] == 50 * GB

    def test_per_volume_isolation(self, tmp_path: Path) -> None:
        db = StorageHistoryDB(db_path=tmp_path / "orpheus.db")
        with patch(
            "orpheus_ui.storage_history.list_storage_volumes",
            return_value=_FAKE_VOLUMES,
        ):
            written = db.sample_now(day="2026-06-04")
        assert written == 2
        assert len(db.history("system", days=30)) == 1
        assert len(db.history("orpheus", days=30)) == 1

    def test_get_storage_history_db_is_cached(self, tmp_path: Path, monkeypatch) -> None:
        """The accessor constructs ONE instance (schema-init/write on the shared live
        DB runs once, not per Diagnostics request). Reset the singleton for isolation."""
        monkeypatch.setattr(
            storage_history_mod, "_default_db_path", lambda: tmp_path / "orpheus.db"
        )
        monkeypatch.setattr(storage_history_mod, "_instance", None)
        first = get_storage_history_db()
        second = get_storage_history_db()
        assert first is second  # not reconstructed (no per-request schema write)

    def test_unreadable_volume_is_skipped(self, tmp_path: Path) -> None:
        bad = [
            {
                "key": "archive", "label": "Archive", "path": "/mnt/archive",
                "total": None, "used": None, "free": None,
                "percent": 0.0, "ok": False, "error": "not mounted",
            }
        ]
        db = StorageHistoryDB(db_path=tmp_path / "orpheus.db")
        with patch(
            "orpheus_ui.storage_history.list_storage_volumes", return_value=bad
        ):
            written = db.sample_now(day="2026-06-04")
        assert written == 0
        assert db.history("archive", days=30) == []
