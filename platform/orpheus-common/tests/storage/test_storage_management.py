"""
Tests for storage management utilities.

Tests cleanup_old_files() and get_disk_usage() functions.
"""

import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from orpheus_common.storage.management import cleanup_old_files, get_disk_usage


class TestCleanupOldFiles:
    """Test the cleanup_old_files function."""

    def test_cleanup_nonexistent_directory(self):
        """Test cleanup on non-existent directory returns 0."""
        result = cleanup_old_files(Path("/nonexistent/path"), max_age_days=30)
        assert result == 0

    def test_cleanup_empty_directory(self):
        """Test cleanup on empty directory returns 0."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = cleanup_old_files(Path(tmpdir), max_age_days=30)
            assert result == 0

    def test_cleanup_dry_run_doesnt_delete(self):
        """Test that dry_run mode doesn't actually delete files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test file
            test_file = Path(tmpdir) / "old_file.txt"
            test_file.write_text("test")

            # Set file to be 31 days old
            old_time = (datetime.now() - timedelta(days=31)).timestamp()
            os.utime(test_file, (old_time, old_time))

            # Run cleanup in dry_run mode
            result = cleanup_old_files(Path(tmpdir), max_age_days=30, dry_run=True)

            assert result == 1
            assert test_file.exists()  # File should still exist

    def test_cleanup_actually_deletes_when_not_dry_run(self):
        """Test that files are actually deleted when dry_run=False."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test file
            test_file = Path(tmpdir) / "old_file.txt"
            test_file.write_text("test")

            # Set file to be 31 days old
            old_time = (datetime.now() - timedelta(days=31)).timestamp()
            os.utime(test_file, (old_time, old_time))

            # Run cleanup
            result = cleanup_old_files(Path(tmpdir), max_age_days=30, dry_run=False)

            assert result == 1
            assert not test_file.exists()  # File should be deleted

    def test_cleanup_preserves_recent_files(self):
        """Test that recent files are not deleted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create recent file
            recent_file = Path(tmpdir) / "recent_file.txt"
            recent_file.write_text("test")

            # Create old file
            old_file = Path(tmpdir) / "old_file.txt"
            old_file.write_text("test")
            old_time = (datetime.now() - timedelta(days=31)).timestamp()
            os.utime(old_file, (old_time, old_time))

            # Run cleanup
            result = cleanup_old_files(Path(tmpdir), max_age_days=30, dry_run=False)

            assert result == 1
            assert recent_file.exists()  # Recent file should remain
            assert not old_file.exists()  # Old file should be deleted

    def test_cleanup_with_pattern_filter(self):
        """Test cleanup with file pattern filtering."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create old .wav file
            wav_file = Path(tmpdir) / "old_audio.wav"
            wav_file.write_text("audio")

            # Create old .txt file
            txt_file = Path(tmpdir) / "old_text.txt"
            txt_file.write_text("text")

            # Make both old
            old_time = (datetime.now() - timedelta(days=31)).timestamp()
            os.utime(wav_file, (old_time, old_time))
            os.utime(txt_file, (old_time, old_time))

            # Cleanup only .wav files
            result = cleanup_old_files(
                Path(tmpdir), max_age_days=30, dry_run=False, pattern="*.wav"
            )

            assert result == 1
            assert not wav_file.exists()  # .wav deleted
            assert txt_file.exists()  # .txt preserved

    def test_cleanup_recursive_subdirectories(self):
        """Test that cleanup works recursively in subdirectories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create nested directory structure
            subdir = Path(tmpdir) / "subdir"
            subdir.mkdir()

            old_file = subdir / "old_file.txt"
            old_file.write_text("test")

            # Make file old
            old_time = (datetime.now() - timedelta(days=31)).timestamp()
            os.utime(old_file, (old_time, old_time))

            # Run cleanup
            result = cleanup_old_files(Path(tmpdir), max_age_days=30, dry_run=False)

            assert result == 1
            assert not old_file.exists()

    def test_cleanup_multiple_old_files(self):
        """Test cleanup of multiple old files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create 5 old files
            old_files = []
            for i in range(5):
                old_file = Path(tmpdir) / f"old_file_{i}.txt"
                old_file.write_text("test")
                old_files.append(old_file)

                old_time = (datetime.now() - timedelta(days=31)).timestamp()
                os.utime(old_file, (old_time, old_time))

            # Run cleanup
            result = cleanup_old_files(Path(tmpdir), max_age_days=30, dry_run=False)

            assert result == 5
            for old_file in old_files:
                assert not old_file.exists()


class TestGetDiskUsage:
    """Test the get_disk_usage function."""

    def test_returns_disk_usage_dict(self):
        """Test that function returns proper disk usage dictionary."""
        with tempfile.TemporaryDirectory() as tmpdir:
            usage = get_disk_usage(Path(tmpdir))

            assert isinstance(usage, dict)
            assert "total_gb" in usage
            assert "used_gb" in usage
            assert "free_gb" in usage
            assert "percent" in usage

    def test_all_values_are_numeric(self):
        """Test that all returned values are numeric."""
        with tempfile.TemporaryDirectory() as tmpdir:
            usage = get_disk_usage(Path(tmpdir))

            assert isinstance(usage["total_gb"], float)
            assert isinstance(usage["used_gb"], float)
            assert isinstance(usage["free_gb"], float)
            assert isinstance(usage["percent"], float)

    def test_values_are_reasonable(self):
        """Test that returned values are within reasonable ranges."""
        with tempfile.TemporaryDirectory() as tmpdir:
            usage = get_disk_usage(Path(tmpdir))

            # Total should be positive
            assert usage["total_gb"] > 0

            # Used should be less than total
            assert usage["used_gb"] < usage["total_gb"]

            # Free should be positive
            assert usage["free_gb"] > 0

            # Percent should be between 0 and 100
            assert 0 <= usage["percent"] <= 100

    def test_percent_calculation(self):
        """Test that percent is calculated correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            usage = get_disk_usage(Path(tmpdir))

            # Percent should be approximately (used / total) * 100
            calculated_percent = (usage["used_gb"] / usage["total_gb"]) * 100
            assert abs(usage["percent"] - calculated_percent) < 0.01

    def test_size_conversion_to_gb(self):
        """Test that sizes are properly converted to GB."""
        with tempfile.TemporaryDirectory() as tmpdir:
            usage = get_disk_usage(Path(tmpdir))

            # All values should be in reasonable GB range for modern systems
            # (even small disks are typically several GB)
            assert usage["total_gb"] >= 1.0
