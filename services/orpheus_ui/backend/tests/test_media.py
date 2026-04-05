"""Tests for media API endpoints (snapshots and timelapses)."""

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestTimelapseEndpoint:
    """Tests for timelapse API endpoints."""

    @pytest.fixture
    def mock_user(self):
        """Create a mock authenticated user."""
        from orpheus_ui.auth.models import User

        user = MagicMock(spec=User)
        user.id = "test-user-id"
        user.email = "test@example.com"
        return user

    @pytest.fixture
    def temp_storage(self):
        """Create a temporary storage directory with timelapse files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = Path(temp_dir)
            timelapse_dir = storage_path / "video" / "timelapses" / "2026.01.24"
            timelapse_dir.mkdir(parents=True)

            # Create new format timelapse files
            new_format_files = [
                "orpheus-eye-1.daily.tl0.24h.20260124-230000.mp4",
                "orpheus-eye-1.hourly.tl3.1h.20260124-180000.mp4",
                "orpheus-eye-2.daily.tl0.24h.20260124-230000.mp4",
            ]
            for filename in new_format_files:
                (timelapse_dir / filename).write_bytes(b"fake mp4 content")

            # Create old format timelapse file
            old_format_file = "18-00.orpheus-eye-1.mp4"
            (timelapse_dir / old_format_file).write_bytes(b"old format mp4")

            yield storage_path

    def test_get_camera_timelapses_finds_new_format_files(self, mock_user, temp_storage):
        """Test that timelapse endpoint finds files with new naming format."""
        from orpheus_ui.api.media import get_camera_timelapses

        mock_config = MagicMock()
        mock_config.storage.base_path = str(temp_storage)

        with patch("orpheus_ui.api.media.OrpheusConfig.get_instance", return_value=mock_config):
            result = get_camera_timelapses(
                camera_name="orpheus-eye-1", date=None, limit=50, user=mock_user
            )

        assert "timelapses" in result
        assert result["count"] >= 2  # At least 2 new format files for eye-1
        filenames = [t["filename"] for t in result["timelapses"]]
        assert any("orpheus-eye-1.daily.tl0.24h" in f for f in filenames)
        assert any("orpheus-eye-1.hourly.tl3.1h" in f for f in filenames)

    def test_get_camera_timelapses_finds_old_format_files(self, mock_user, temp_storage):
        """Test that timelapse endpoint still finds files with old naming format."""
        from orpheus_ui.api.media import get_camera_timelapses

        mock_config = MagicMock()
        mock_config.storage.base_path = str(temp_storage)

        with patch("orpheus_ui.api.media.OrpheusConfig.get_instance", return_value=mock_config):
            result = get_camera_timelapses(
                camera_name="orpheus-eye-1", date=None, limit=50, user=mock_user
            )

        filenames = [t["filename"] for t in result["timelapses"]]
        assert any("18-00.orpheus-eye-1.mp4" in f for f in filenames)

    def test_get_camera_timelapses_parses_metadata(self, mock_user, temp_storage):
        """Test that timelapse endpoint parses metadata from new format filenames."""
        from orpheus_ui.api.media import get_camera_timelapses

        mock_config = MagicMock()
        mock_config.storage.base_path = str(temp_storage)

        with patch("orpheus_ui.api.media.OrpheusConfig.get_instance", return_value=mock_config):
            result = get_camera_timelapses(
                camera_name="orpheus-eye-1", date=None, limit=50, user=mock_user
            )

        # Find the daily tl0 file
        daily_file = next((t for t in result["timelapses"] if "daily.tl0" in t["filename"]), None)
        assert daily_file is not None
        assert daily_file["label"] == "daily"
        assert daily_file["tier"] == "tl0"
        assert daily_file["tier_display"] == "24h"
        assert daily_file["lookback"] == "24h"

    def test_get_camera_timelapses_sorts_by_tier(self, mock_user, temp_storage):
        """Test that timelapses are sorted by tier (24h first, then 1h, etc.)."""
        from orpheus_ui.api.media import get_camera_timelapses

        mock_config = MagicMock()
        mock_config.storage.base_path = str(temp_storage)

        with patch("orpheus_ui.api.media.OrpheusConfig.get_instance", return_value=mock_config):
            result = get_camera_timelapses(
                camera_name="orpheus-eye-1", date=None, limit=50, user=mock_user
            )

        # tl0 (24h) files should come before tl3 (1h) files
        tiers = [t.get("tier") for t in result["timelapses"] if t.get("tier")]
        if "tl0" in tiers and "tl3" in tiers:
            first_tl0_idx = tiers.index("tl0")
            first_tl3_idx = tiers.index("tl3")
            assert first_tl0_idx < first_tl3_idx, "tl0 (24h) should come before tl3 (1h)"

    def test_get_camera_timelapses_filters_by_camera(self, mock_user, temp_storage):
        """Test that timelapse endpoint only returns files for the requested camera."""
        from orpheus_ui.api.media import get_camera_timelapses

        mock_config = MagicMock()
        mock_config.storage.base_path = str(temp_storage)

        with patch("orpheus_ui.api.media.OrpheusConfig.get_instance", return_value=mock_config):
            result = get_camera_timelapses(
                camera_name="orpheus-eye-2", date=None, limit=50, user=mock_user
            )

        # Should only find eye-2 files
        assert result["count"] == 1
        assert "orpheus-eye-2" in result["timelapses"][0]["filename"]

    def test_get_camera_timelapses_filters_by_date(self, mock_user, temp_storage):
        """Test that timelapse endpoint filters by date when specified."""
        from orpheus_ui.api.media import get_camera_timelapses

        mock_config = MagicMock()
        mock_config.storage.base_path = str(temp_storage)

        with patch("orpheus_ui.api.media.OrpheusConfig.get_instance", return_value=mock_config):
            # Request a date that has no files
            result = get_camera_timelapses(
                camera_name="orpheus-eye-1", date="2026.01.25", limit=50, user=mock_user
            )

        assert result["count"] == 0
        assert result["timelapses"] == []

    def test_get_camera_timelapses_returns_download_url(self, mock_user, temp_storage):
        """Test that timelapse endpoint returns valid download URLs."""
        from orpheus_ui.api.media import get_camera_timelapses

        mock_config = MagicMock()
        mock_config.storage.base_path = str(temp_storage)

        with patch("orpheus_ui.api.media.OrpheusConfig.get_instance", return_value=mock_config):
            result = get_camera_timelapses(
                camera_name="orpheus-eye-1", date=None, limit=50, user=mock_user
            )

        for timelapse in result["timelapses"]:
            assert "download_url" in timelapse
            assert timelapse["download_url"].startswith("/api/media/timelapses/")
            assert "orpheus-eye-1" in timelapse["download_url"]

    def test_get_camera_timelapses_rejects_path_traversal(self, mock_user, temp_storage):
        """Test that timelapse endpoint rejects path traversal attempts."""
        from fastapi import HTTPException

        from orpheus_ui.api.media import get_camera_timelapses

        mock_config = MagicMock()
        mock_config.storage.base_path = str(temp_storage)

        with patch("orpheus_ui.api.media.OrpheusConfig.get_instance", return_value=mock_config):
            with pytest.raises(HTTPException) as exc_info:
                get_camera_timelapses(camera_name="../etc", date=None, limit=50, user=mock_user)
            assert exc_info.value.status_code == 400

            with pytest.raises(HTTPException) as exc_info:
                get_camera_timelapses(
                    camera_name="camera/name", date=None, limit=50, user=mock_user
                )
            assert exc_info.value.status_code == 400

    def test_get_camera_timelapses_empty_directory(self, mock_user):
        """Test that timelapse endpoint handles missing directory gracefully."""
        from orpheus_ui.api.media import get_camera_timelapses

        with tempfile.TemporaryDirectory() as temp_dir:
            mock_config = MagicMock()
            mock_config.storage.base_path = temp_dir

            with patch("orpheus_ui.api.media.OrpheusConfig.get_instance", return_value=mock_config):
                result = get_camera_timelapses(
                    camera_name="orpheus-eye-1", date=None, limit=50, user=mock_user
                )

            assert result["timelapses"] == []
            assert result["camera"] == "orpheus-eye-1"

    def test_get_camera_timelapses_default_limit_is_1000(self, mock_user, temp_storage):
        """Test that the default limit is 1000 (not 50)."""
        import inspect

        from orpheus_ui.api.media import get_camera_timelapses

        sig = inspect.signature(get_camera_timelapses)
        assert sig.parameters["limit"].default == 1000

    def test_get_camera_timelapses_limit_zero_returns_all(self, mock_user, temp_storage):
        """Test that limit=0 returns all files (unlimited)."""
        from orpheus_ui.api.media import get_camera_timelapses

        mock_config = MagicMock()
        mock_config.storage.base_path = str(temp_storage)

        with patch("orpheus_ui.api.media.OrpheusConfig.get_instance", return_value=mock_config):
            result = get_camera_timelapses(
                camera_name="orpheus-eye-1", date=None, limit=0, user=mock_user
            )

        # With limit=0 (unlimited), should return all matching files for eye-1
        # That's: daily, hourly, and old format = 3 files
        assert result["count"] == 3

    def test_get_camera_timelapses_limit_applied_after_sort(self, mock_user, temp_storage):
        """Test that limit is applied after tier-based sorting, not during collection.

        This verifies the bug fix: previously, sorted(glob, reverse=True) with an
        early break caused daily/hourly files to be dropped before they could be
        collected. Now all files are gathered first, sorted by tier, then sliced.
        """
        from orpheus_ui.api.media import get_camera_timelapses

        mock_config = MagicMock()
        mock_config.storage.base_path = str(temp_storage)

        with patch("orpheus_ui.api.media.OrpheusConfig.get_instance", return_value=mock_config):
            # Use limit=2 -- should get the two highest-priority tier files (tl0)
            result = get_camera_timelapses(
                camera_name="orpheus-eye-1", date=None, limit=2, user=mock_user
            )

        assert result["count"] == 2
        # Both results should be tl0 tier (daily + legacy both parse as tl0)
        assert all(t["tier"] == "tl0" for t in result["timelapses"])
        # Verify both daily and legacy labels are present (neither was dropped)
        labels = {t["label"] for t in result["timelapses"]}
        assert "daily" in labels
        assert "legacy" in labels

    def test_get_camera_timelapses_collects_all_labels(self, mock_user, temp_storage):
        """Test that all label types (daily, hourly) are collected without being dropped."""
        from orpheus_ui.api.media import get_camera_timelapses

        mock_config = MagicMock()
        mock_config.storage.base_path = str(temp_storage)

        with patch("orpheus_ui.api.media.OrpheusConfig.get_instance", return_value=mock_config):
            result = get_camera_timelapses(
                camera_name="orpheus-eye-1", date=None, limit=1000, user=mock_user
            )

        labels = [t.get("label") for t in result["timelapses"]]
        assert "daily" in labels, "daily label should be present"
        assert "hourly" in labels, "hourly label should be present"

    def test_get_camera_timelapses_limit_2_gets_top_tier_files(self, mock_user, temp_storage):
        """Test that with limit=2, we get the two highest-priority files after sorting."""
        from orpheus_ui.api.media import get_camera_timelapses

        mock_config = MagicMock()
        mock_config.storage.base_path = str(temp_storage)

        with patch("orpheus_ui.api.media.OrpheusConfig.get_instance", return_value=mock_config):
            result = get_camera_timelapses(
                camera_name="orpheus-eye-1", date=None, limit=2, user=mock_user
            )

        assert result["count"] == 2
        # First should be tl0 (daily/24h), second should be tl3 (hourly/1h) or legacy
        tiers = [t.get("tier") for t in result["timelapses"]]
        assert tiers[0] == "tl0"


class TestSnapshotEndpoint:
    """Tests for snapshot API endpoints."""

    @pytest.fixture
    def mock_user(self):
        """Create a mock authenticated user."""
        from orpheus_ui.auth.models import User

        user = MagicMock(spec=User)
        user.id = "test-user-id"
        user.email = "test@example.com"
        return user

    @pytest.fixture
    def temp_storage(self):
        """Create a temporary storage directory with snapshot files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = Path(temp_dir)
            today = datetime.now(timezone.utc).strftime("%Y.%m.%d")
            snapshot_dir = storage_path / "video" / "snapshots" / today
            snapshot_dir.mkdir(parents=True)

            # Create snapshot files
            snapshot_files = [
                "2026-01-25T10-00-00.000Z.orpheus-eye-1.jpg",
                "2026-01-25T10-05-00.000Z.orpheus-eye-1.jpg",
                "2026-01-25T10-00-00.000Z.orpheus-eye-2.jpg",
            ]
            for filename in snapshot_files:
                (snapshot_dir / filename).write_bytes(b"fake jpg content")

            yield storage_path

    def test_get_camera_snapshots_filters_by_camera(self, mock_user, temp_storage):
        """Test that snapshot endpoint filters by camera name."""
        from orpheus_ui.api.media import get_camera_snapshots

        mock_config = MagicMock()
        mock_config.storage.base_path = str(temp_storage)

        with patch("orpheus_ui.api.media.OrpheusConfig.get_instance", return_value=mock_config):
            result = get_camera_snapshots(
                camera_name="orpheus-eye-1", date=None, limit=50, user=mock_user
            )

        assert result["count"] == 2
        for snapshot in result["snapshots"]:
            assert "orpheus-eye-1" in snapshot["filename"]
