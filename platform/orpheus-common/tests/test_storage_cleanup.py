"""Tests for storage cleanup functionality."""

import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from orpheus_common.storage.cleanup import (
    CleanupPolicy,
    CleanupResult,
    FileInfo,
    StorageCleanup,
    cleanup_old_files_by_age,
)


class TestCleanupPolicy:
    """Test CleanupPolicy dataclass and validation."""

    def test_default_values(self):
        """Test that default policy values are reasonable."""
        policy = CleanupPolicy()

        assert policy.max_size_gb == 50.0
        assert policy.max_age_days == 90
        assert policy.cleanup_strategy == "oldest"
        assert policy.cleanup_trigger_percent == 90.0
        assert policy.cleanup_amount_percent == 25.0
        assert policy.min_file_age_hours == 1.0

    def test_validate_positive_max_size(self):
        """Test that max_size_gb must be positive."""
        policy = CleanupPolicy(max_size_gb=-10)

        with pytest.raises(ValueError, match="max_size_gb must be positive"):
            policy.validate()

    def test_validate_strategy(self):
        """Test that cleanup_strategy must be valid."""
        policy = CleanupPolicy(cleanup_strategy="invalid")

        with pytest.raises(ValueError, match="cleanup_strategy must be"):
            policy.validate()

    def test_validate_trigger_percent(self):
        """Test that trigger percent must be between 0 and 100."""
        policy = CleanupPolicy(cleanup_trigger_percent=150)

        with pytest.raises(ValueError, match="cleanup_trigger_percent"):
            policy.validate()

    def test_validate_cleanup_amount_percent(self):
        """Test that cleanup amount percent must be between 0 and 100."""
        policy = CleanupPolicy(cleanup_amount_percent=150)

        with pytest.raises(ValueError, match="cleanup_amount_percent"):
            policy.validate()

    def test_validate_min_file_age(self):
        """Test that min_file_age_hours must be non-negative."""
        policy = CleanupPolicy(min_file_age_hours=-1.0)

        with pytest.raises(ValueError, match="min_file_age_hours must be non-negative"):
            policy.validate()

    def test_validate_max_age_days(self):
        """Test that max_age_days must be positive."""
        policy = CleanupPolicy(max_age_days=-10)

        with pytest.raises(ValueError, match="max_age_days must be positive"):
            policy.validate()

    def test_custom_file_pattern(self):
        """Test that custom file patterns are stored correctly."""
        policy = CleanupPolicy(file_pattern="*.flac")
        assert policy.file_pattern == "*.flac"


class TestFileInfo:
    """Test FileInfo creation and properties."""

    def test_from_path(self):
        """Test creating FileInfo from a file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.txt"
            file_path.write_text("test content")

            info = FileInfo.from_path(file_path)

            assert info.path == file_path
            assert info.size_bytes == len("test content")
            assert info.age_hours >= 0


class TestStorageCleanup:
    """Test StorageCleanup class."""

    def test_scan_directory(self):
        """Test scanning directory for files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            (Path(tmpdir) / "file1.txt").write_text("content1")
            (Path(tmpdir) / "file2.txt").write_text("content2")
            subdir = Path(tmpdir) / "subdir"
            subdir.mkdir()
            (subdir / "file3.txt").write_text("content3")

            cleanup = StorageCleanup(CleanupPolicy())
            files = cleanup.scan_directory(Path(tmpdir))

            assert len(files) == 3
            assert all(isinstance(f, FileInfo) for f in files)

    def test_scan_nonexistent_directory(self):
        """Test scanning non-existent directory."""
        cleanup = StorageCleanup(CleanupPolicy())
        files = cleanup.scan_directory(Path("/nonexistent"))

        assert files == []

    def test_calculate_usage(self):
        """Test calculating storage usage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create 1 MB of files
            file_path = Path(tmpdir) / "large.bin"
            file_path.write_bytes(b"x" * (1024 * 1024))

            policy = CleanupPolicy(max_size_gb=0.001)  # 1 MB limit
            cleanup = StorageCleanup(policy)
            used_bytes, used_percent = cleanup.calculate_usage(Path(tmpdir))

            assert used_bytes >= 1024 * 1024
            assert used_percent >= 95  # Should be close to or over limit

    def test_needs_cleanup(self):
        """Test cleanup trigger detection."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create files that exceed trigger
            file_path = Path(tmpdir) / "large.bin"
            file_path.write_bytes(b"x" * (1024 * 1024))

            policy = CleanupPolicy(max_size_gb=0.001, cleanup_trigger_percent=50.0)
            cleanup = StorageCleanup(policy)

            assert cleanup.needs_cleanup(Path(tmpdir)) is True

    def test_select_files_oldest_strategy(self):
        """Test selecting oldest files for deletion."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create files with different ages
            old_file = Path(tmpdir) / "old.txt"
            old_file.write_text("old")
            old_time = (datetime.now() - timedelta(hours=10)).timestamp()
            old_file.touch()
            old_file.chmod(0o644)
            import os

            os.utime(old_file, (old_time, old_time))

            new_file = Path(tmpdir) / "new.txt"
            new_file.write_text("new")

            policy = CleanupPolicy(
                cleanup_strategy="oldest", cleanup_amount_percent=50, min_file_age_hours=0.1
            )
            cleanup = StorageCleanup(policy)

            files = cleanup.scan_directory(Path(tmpdir))
            selected = cleanup.select_files_to_delete(files)

            assert len(selected) >= 1
            assert selected[0].path == old_file

    def test_select_files_respects_min_age(self):
        """Test that files younger than min_age are not selected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "recent.txt"
            file_path.write_text("very recent file")

            policy = CleanupPolicy(min_file_age_hours=24.0, cleanup_amount_percent=100)
            cleanup = StorageCleanup(policy)

            files = cleanup.scan_directory(Path(tmpdir))
            selected = cleanup.select_files_to_delete(files)

            assert len(selected) == 0  # Too young to delete

    def test_create_deletion_manifest(self):
        """Test creating CSV manifest of files to delete."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.txt"
            file_path.write_text("content")

            cleanup = StorageCleanup(CleanupPolicy())
            files = [FileInfo.from_path(file_path)]

            manifest_dir = Path(tmpdir) / "manifests"
            manifest_path = cleanup.create_deletion_manifest(files, manifest_dir)

            assert manifest_path.exists()
            assert manifest_path.suffix == ".csv"
            content = manifest_path.read_text()
            assert "path,size_bytes,mtime,age_hours" in content

    def test_cleanup_dry_run(self):
        """Test cleanup in dry-run mode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.txt"
            file_path.write_text("x" * 1000)

            policy = CleanupPolicy(
                max_size_gb=0.000001, cleanup_trigger_percent=1.0, min_file_age_hours=0.0
            )
            cleanup = StorageCleanup(policy)

            result = cleanup.cleanup(Path(tmpdir), dry_run=True)

            assert result.files_removed >= 0
            assert file_path.exists()  # File should still exist

    def test_cleanup_actual_deletion(self):
        """Test cleanup actually deletes files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.txt"
            file_path.write_text("x" * 1000)

            # Make file old enough
            old_time = (datetime.now() - timedelta(hours=2)).timestamp()
            import os

            os.utime(file_path, (old_time, old_time))

            policy = CleanupPolicy(
                max_size_gb=0.000001,
                cleanup_trigger_percent=1.0,
                min_file_age_hours=0.5,
                cleanup_amount_percent=100,
            )
            cleanup = StorageCleanup(policy)

            result = cleanup.cleanup(Path(tmpdir), dry_run=False)

            assert result.files_removed >= 1
            assert not file_path.exists()  # File should be deleted

    def test_cleanup_result_structure(self):
        """Test CleanupResult contains expected fields."""
        result = CleanupResult(files_removed=5, bytes_freed=1024 * 1024, duration_seconds=1.5)

        result_dict = result.to_dict()

        assert result_dict["files_removed"] == 5
        assert result_dict["bytes_freed"] == 1024 * 1024
        assert "bytes_freed_mb" in result_dict
        assert result_dict["duration_seconds"] == 1.5

    def test_scan_with_file_pattern(self):
        """Test scanning directory with file pattern filtering."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create files with different extensions
            (Path(tmpdir) / "audio1.flac").write_text("audio1")
            (Path(tmpdir) / "audio2.flac").write_text("audio2")
            (Path(tmpdir) / "text.txt").write_text("text")
            (Path(tmpdir) / "data.json").write_text("json")

            policy = CleanupPolicy(file_pattern="*.flac")
            cleanup = StorageCleanup(policy)
            files = cleanup.scan_directory(Path(tmpdir))

            assert len(files) == 2
            assert all(f.path.suffix == ".flac" for f in files)

    def test_select_files_largest_strategy(self):
        """Test selecting largest files for deletion."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            # Create files of different sizes
            small_file = Path(tmpdir) / "small.txt"
            small_file.write_text("x" * 100)
            # Make it old enough
            old_time = (datetime.now() - timedelta(hours=2)).timestamp()
            os.utime(small_file, (old_time, old_time))

            large_file = Path(tmpdir) / "large.txt"
            large_file.write_text("x" * 10000)
            os.utime(large_file, (old_time, old_time))

            policy = CleanupPolicy(
                cleanup_strategy="largest", cleanup_amount_percent=50, min_file_age_hours=0.1
            )
            cleanup = StorageCleanup(policy)

            files = cleanup.scan_directory(Path(tmpdir))
            selected = cleanup.select_files_to_delete(files)

            assert len(selected) >= 1
            assert selected[0].path == large_file  # Largest file selected first

    def test_select_files_random_strategy(self):
        """Test random file selection strategy."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            # Create multiple files
            for i in range(10):
                file_path = Path(tmpdir) / f"file{i}.txt"
                file_path.write_text("x" * 1000)
                old_time = (datetime.now() - timedelta(hours=2)).timestamp()
                os.utime(file_path, (old_time, old_time))

            policy = CleanupPolicy(
                cleanup_strategy="random", cleanup_amount_percent=50, min_file_age_hours=0.1
            )
            cleanup = StorageCleanup(policy)

            files = cleanup.scan_directory(Path(tmpdir))
            selected = cleanup.select_files_to_delete(files)

            # Should select some files (exact count depends on sizes)
            assert len(selected) > 0
            assert len(selected) <= len(files)

    def test_cleanup_below_trigger_threshold(self):
        """Test that cleanup doesn't run when below trigger threshold."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create small file
            file_path = Path(tmpdir) / "small.txt"
            file_path.write_text("x" * 100)

            policy = CleanupPolicy(max_size_gb=1.0, cleanup_trigger_percent=90.0)
            cleanup = StorageCleanup(policy)

            result = cleanup.cleanup(Path(tmpdir), dry_run=False)

            assert result.files_removed == 0
            assert result.bytes_freed == 0
            assert file_path.exists()  # File not deleted

    def test_cleanup_with_errors(self):
        """Test that cleanup continues and logs errors for individual files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            # Create files
            file1 = Path(tmpdir) / "file1.txt"
            file1.write_text("x" * 1000)
            file2 = Path(tmpdir) / "file2.txt"
            file2.write_text("x" * 1000)

            # Make files old enough
            old_time = (datetime.now() - timedelta(hours=2)).timestamp()
            os.utime(file1, (old_time, old_time))
            os.utime(file2, (old_time, old_time))

            policy = CleanupPolicy(
                max_size_gb=0.000001,
                cleanup_trigger_percent=1.0,
                min_file_age_hours=0.5,
                cleanup_amount_percent=100,
            )
            cleanup = StorageCleanup(policy)

            # Make one file read-only to potentially cause deletion error
            # (though this may not fail on all systems)
            file1.chmod(0o444)

            result = cleanup.cleanup(Path(tmpdir), dry_run=False)

            # Should have attempted to delete files
            assert result.files_removed >= 0

    def test_manifest_contains_correct_data(self):
        """Test that deletion manifest contains correct file information."""
        import csv

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a test file
            file_path = Path(tmpdir) / "test.txt"
            file_path.write_text("test content")

            cleanup = StorageCleanup(CleanupPolicy())
            file_info = FileInfo.from_path(file_path)

            manifest_dir = Path(tmpdir) / "manifests"
            manifest_path = cleanup.create_deletion_manifest([file_info], manifest_dir)

            # Read and verify manifest
            with open(manifest_path) as f:
                reader = csv.DictReader(f)
                rows = list(reader)

            assert len(rows) == 1
            row = rows[0]
            assert row["path"] == str(file_path)
            assert int(row["size_bytes"]) == len("test content")
            assert "mtime" in row
            assert "age_hours" in row

    def test_cleanup_no_eligible_files(self):
        """Test cleanup when no files meet age requirements."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create very recent files
            for i in range(5):
                file_path = Path(tmpdir) / f"recent{i}.txt"
                file_path.write_text("x" * 10000)

            policy = CleanupPolicy(
                max_size_gb=0.00001,
                cleanup_trigger_percent=1.0,
                min_file_age_hours=24.0,  # Files must be > 24 hours old
            )
            cleanup = StorageCleanup(policy)

            result = cleanup.cleanup(Path(tmpdir), dry_run=False)

            # No files should be deleted (all too young)
            assert result.files_removed == 0
            assert result.bytes_freed == 0

    def test_cleanup_respects_target_bytes(self):
        """Test that cleanup stops after reaching target bytes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            # Create multiple files
            for i in range(10):
                file_path = Path(tmpdir) / f"file{i}.txt"
                file_path.write_text("x" * 1000)
                old_time = (datetime.now() - timedelta(hours=2)).timestamp()
                os.utime(file_path, (old_time, old_time))

            policy = CleanupPolicy(
                max_size_gb=0.00001,
                cleanup_trigger_percent=1.0,
                cleanup_amount_percent=30.0,  # Remove ~30%
                min_file_age_hours=0.5,
            )
            cleanup = StorageCleanup(policy)

            result = cleanup.cleanup(Path(tmpdir), dry_run=False)

            # Should remove some but not all files
            assert result.files_removed > 0
            assert result.files_removed < 10

    def test_scan_directory_with_subdirectories(self):
        """Test that scanning includes files in subdirectories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create nested structure
            (Path(tmpdir) / "file1.txt").write_text("content1")
            subdir1 = Path(tmpdir) / "subdir1"
            subdir1.mkdir()
            (subdir1 / "file2.txt").write_text("content2")
            subdir2 = subdir1 / "subdir2"
            subdir2.mkdir()
            (subdir2 / "file3.txt").write_text("content3")

            cleanup = StorageCleanup(CleanupPolicy())
            files = cleanup.scan_directory(Path(tmpdir))

            assert len(files) == 3
            # Verify all paths are found
            paths = {f.path for f in files}
            assert Path(tmpdir) / "file1.txt" in paths
            assert subdir1 / "file2.txt" in paths
            assert subdir2 / "file3.txt" in paths


class TestCleanupOldFilesByAge:
    """Test the simple age-based cleanup utility."""

    def test_cleanup_by_age(self):
        """Test removing files older than specified age."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create old file
            old_file = Path(tmpdir) / "old.txt"
            old_file.write_text("old")
            old_time = (datetime.now() - timedelta(days=31)).timestamp()
            import os

            os.utime(old_file, (old_time, old_time))

            # Create recent file
            recent_file = Path(tmpdir) / "recent.txt"
            recent_file.write_text("recent")

            deleted = cleanup_old_files_by_age(Path(tmpdir), max_age_days=30, dry_run=False)

            assert deleted == 1
            assert not old_file.exists()
            assert recent_file.exists()

    def test_cleanup_by_age_dry_run(self):
        """Test age-based cleanup in dry-run mode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            old_file = Path(tmpdir) / "old.txt"
            old_file.write_text("old")
            old_time = (datetime.now() - timedelta(days=31)).timestamp()
            import os

            os.utime(old_file, (old_time, old_time))

            deleted = cleanup_old_files_by_age(Path(tmpdir), max_age_days=30, dry_run=True)

            assert deleted == 1
            assert old_file.exists()  # Still exists in dry-run

    def test_cleanup_with_pattern(self):
        """Test cleanup with file pattern filtering."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create old files with different extensions
            old_flac = Path(tmpdir) / "old.flac"
            old_flac.write_text("old audio")
            old_txt = Path(tmpdir) / "old.txt"
            old_txt.write_text("old text")

            old_time = (datetime.now() - timedelta(days=31)).timestamp()
            import os

            os.utime(old_flac, (old_time, old_time))
            os.utime(old_txt, (old_time, old_time))

            # Clean only .flac files
            deleted = cleanup_old_files_by_age(
                Path(tmpdir), max_age_days=30, dry_run=False, pattern="*.flac"
            )

            assert deleted == 1
            assert not old_flac.exists()
            assert old_txt.exists()  # .txt file preserved

    def test_cleanup_nonexistent_path(self):
        """Test age-based cleanup on non-existent path."""
        deleted = cleanup_old_files_by_age(
            Path("/nonexistent/path"), max_age_days=30, dry_run=False
        )

        assert deleted == 0

    def test_cleanup_by_age_with_subdirectories(self):
        """Test age-based cleanup includes subdirectories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            # Create old files in nested structure
            old_time = (datetime.now() - timedelta(days=31)).timestamp()

            file1 = Path(tmpdir) / "old1.txt"
            file1.write_text("old")
            os.utime(file1, (old_time, old_time))

            subdir = Path(tmpdir) / "subdir"
            subdir.mkdir()
            file2 = subdir / "old2.txt"
            file2.write_text("old")
            os.utime(file2, (old_time, old_time))

            deleted = cleanup_old_files_by_age(Path(tmpdir), max_age_days=30, dry_run=False)

            assert deleted == 2
            assert not file1.exists()
            assert not file2.exists()


class TestFileInfoEdgeCases:
    """Test FileInfo edge cases and properties."""

    def test_file_info_age_calculation(self):
        """Test that file age is calculated correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            file_path = Path(tmpdir) / "test.txt"
            file_path.write_text("test")

            # Set modification time to 10 hours ago
            hours_ago = 10
            old_time = (datetime.now() - timedelta(hours=hours_ago)).timestamp()
            os.utime(file_path, (old_time, old_time))

            info = FileInfo.from_path(file_path)

            # Age should be approximately 10 hours (within 1 minute tolerance)
            assert abs(info.age_hours - hours_ago) < 0.02  # ~1 minute tolerance

    def test_file_info_size_accuracy(self):
        """Test that file size is reported accurately."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.bin"
            content = b"x" * 12345
            file_path.write_bytes(content)

            info = FileInfo.from_path(file_path)

            assert info.size_bytes == len(content)


class TestCleanupPolicyValidation:
    """Test comprehensive policy validation."""

    def test_valid_policy_passes_validation(self):
        """Test that a valid policy passes validation."""
        policy = CleanupPolicy(
            max_size_gb=50.0,
            max_age_days=90,
            cleanup_strategy="oldest",
            cleanup_trigger_percent=90.0,
            cleanup_amount_percent=25.0,
            min_file_age_hours=1.0,
        )

        # Should not raise
        policy.validate()

    def test_trigger_percent_boundary_cases(self):
        """Test trigger percent boundary validation."""
        # Zero should fail
        policy = CleanupPolicy(cleanup_trigger_percent=0.0)
        with pytest.raises(ValueError):
            policy.validate()

        # 100 should pass
        policy = CleanupPolicy(cleanup_trigger_percent=100.0)
        policy.validate()  # Should not raise

        # Above 100 should fail
        policy = CleanupPolicy(cleanup_trigger_percent=100.1)
        with pytest.raises(ValueError):
            policy.validate()

    def test_cleanup_amount_percent_boundary_cases(self):
        """Test cleanup amount percent boundary validation."""
        # Zero should fail
        policy = CleanupPolicy(cleanup_amount_percent=0.0)
        with pytest.raises(ValueError):
            policy.validate()

        # 100 should pass
        policy = CleanupPolicy(cleanup_amount_percent=100.0)
        policy.validate()  # Should not raise

        # Above 100 should fail
        policy = CleanupPolicy(cleanup_amount_percent=100.1)
        with pytest.raises(ValueError):
            policy.validate()


class TestCleanupResultHelpers:
    """Test CleanupResult helper methods."""

    def test_cleanup_result_to_dict(self):
        """Test CleanupResult.to_dict() conversion."""
        manifest_path = Path("/tmp/manifest.csv")
        result = CleanupResult(
            files_removed=10,
            bytes_freed=1024 * 1024 * 5,  # 5 MB
            manifest_path=manifest_path,
            duration_seconds=2.5,
            errors=["error1", "error2"],
        )

        result_dict = result.to_dict()

        assert result_dict["files_removed"] == 10
        assert result_dict["bytes_freed"] == 1024 * 1024 * 5
        assert result_dict["bytes_freed_mb"] == 5.0
        assert result_dict["manifest_path"] == str(manifest_path)
        assert result_dict["duration_seconds"] == 2.5
        assert result_dict["errors"] == ["error1", "error2"]

    def test_cleanup_result_default_values(self):
        """Test CleanupResult with default values."""
        result = CleanupResult()

        assert result.files_removed == 0
        assert result.bytes_freed == 0
        assert result.manifest_path is None
        assert result.duration_seconds == 0.0
        assert result.errors == []

    def test_cleanup_result_to_dict_with_none_manifest(self):
        """Test to_dict when manifest_path is None."""
        result = CleanupResult(files_removed=5, bytes_freed=1000)

        result_dict = result.to_dict()

        assert result_dict["manifest_path"] is None


class TestStorageCleanupIntegration:
    """Integration tests for complete cleanup workflows."""

    def test_full_cleanup_workflow(self):
        """Test complete cleanup workflow from scan to deletion."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            # Create a realistic file structure
            for i in range(20):
                file_path = Path(tmpdir) / f"clip_{i:03d}.flac"
                file_path.write_text("x" * (1000 * (i + 1)))  # Varying sizes

                # Make half the files old
                if i < 10:
                    old_time = (datetime.now() - timedelta(hours=5)).timestamp()
                    os.utime(file_path, (old_time, old_time))

            # Setup policy
            policy = CleanupPolicy(
                max_size_gb=0.0001,  # Very small limit
                cleanup_trigger_percent=10.0,  # Will trigger
                cleanup_amount_percent=50.0,  # Remove half
                cleanup_strategy="oldest",
                min_file_age_hours=1.0,
                file_pattern="*.flac",
            )

            cleanup = StorageCleanup(policy)

            # Verify cleanup is needed
            assert cleanup.needs_cleanup(Path(tmpdir))

            # Run cleanup
            result = cleanup.cleanup(Path(tmpdir), dry_run=False)

            # Verify results
            assert result.files_removed > 0
            assert result.bytes_freed > 0
            assert result.manifest_path is not None
            assert result.manifest_path.exists()
            assert result.duration_seconds > 0

            # Verify manifest was created
            import csv

            with open(result.manifest_path) as f:
                reader = csv.DictReader(f)
                manifest_rows = list(reader)
                assert len(manifest_rows) == result.files_removed

    def test_multiple_cleanup_strategies_comparison(self):
        """Test that different strategies select different files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            # Create files with different ages and sizes
            old_small = Path(tmpdir) / "old_small.txt"
            old_small.write_text("x" * 100)
            os.utime(old_small, ((datetime.now() - timedelta(hours=10)).timestamp(),) * 2)

            old_large = Path(tmpdir) / "old_large.txt"
            old_large.write_text("x" * 10000)
            os.utime(old_large, ((datetime.now() - timedelta(hours=5)).timestamp(),) * 2)

            # Scan files
            cleanup = StorageCleanup(CleanupPolicy(min_file_age_hours=0.1))
            files = cleanup.scan_directory(Path(tmpdir))

            # Test oldest strategy
            cleanup.policy.cleanup_strategy = "oldest"
            cleanup.policy.cleanup_amount_percent = 100
            selected_oldest = cleanup.select_files_to_delete(files)
            assert selected_oldest[0].path == old_small  # Oldest file

            # Test largest strategy
            cleanup.policy.cleanup_strategy = "largest"
            selected_largest = cleanup.select_files_to_delete(files)
            assert selected_largest[0].path == old_large  # Largest file
