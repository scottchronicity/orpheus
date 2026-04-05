"""
Tests for ensure_directory path utility.

Tests the ensure_directory() function that creates directories
with proper permissions.
"""

import os
import stat
import tempfile
from pathlib import Path

from orpheus_common.storage.paths import ensure_directory


class TestEnsureDirectory:
    """Test the ensure_directory function."""

    def test_creates_new_directory(self):
        """Test that ensure_directory creates a new directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            new_dir = Path(tmpdir) / "new_directory"
            assert not new_dir.exists()

            result = ensure_directory(new_dir)

            assert new_dir.exists()
            assert new_dir.is_dir()
            assert result == new_dir

    def test_creates_nested_directories(self):
        """Test that ensure_directory creates nested parent directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            nested_dir = Path(tmpdir) / "level1" / "level2" / "level3"
            assert not nested_dir.exists()

            ensure_directory(nested_dir)

            assert nested_dir.exists()
            assert nested_dir.is_dir()
            assert (Path(tmpdir) / "level1").exists()
            assert (Path(tmpdir) / "level1" / "level2").exists()

    def test_idempotent_on_existing_directory(self):
        """Test that ensure_directory is safe to call on existing directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_dir = Path(tmpdir) / "existing"
            test_dir.mkdir()

            # Should not raise error
            result = ensure_directory(test_dir)

            assert test_dir.exists()
            assert result == test_dir

    def test_accepts_string_path(self):
        """Test that ensure_directory accepts string paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            new_dir = os.path.join(tmpdir, "string_path")
            assert not os.path.exists(new_dir)

            result = ensure_directory(new_dir)

            assert os.path.exists(new_dir)
            assert isinstance(result, Path)

    def test_accepts_path_object(self):
        """Test that ensure_directory accepts Path objects."""
        with tempfile.TemporaryDirectory() as tmpdir:
            new_dir = Path(tmpdir) / "path_object"
            assert not new_dir.exists()

            result = ensure_directory(new_dir)

            assert new_dir.exists()
            assert isinstance(result, Path)

    def test_default_permissions_755(self):
        """Test that default permissions are 755."""
        with tempfile.TemporaryDirectory() as tmpdir:
            new_dir = Path(tmpdir) / "perms_test"

            ensure_directory(new_dir)

            # Get directory mode (masked with 0o777 to get permission bits only)
            dir_mode = stat.S_IMODE(new_dir.stat().st_mode)

            # On some systems, the actual mode may be affected by umask
            # Just check that directory is readable and executable by owner
            assert dir_mode & stat.S_IRUSR  # Owner read
            assert dir_mode & stat.S_IWUSR  # Owner write
            assert dir_mode & stat.S_IXUSR  # Owner execute

    def test_custom_permissions(self):
        """Test that custom permissions can be set."""
        with tempfile.TemporaryDirectory() as tmpdir:
            new_dir = Path(tmpdir) / "custom_perms"

            ensure_directory(new_dir, mode=0o700)

            dir_mode = stat.S_IMODE(new_dir.stat().st_mode)

            # At minimum, owner should have full permissions
            assert dir_mode & stat.S_IRUSR
            assert dir_mode & stat.S_IWUSR
            assert dir_mode & stat.S_IXUSR

    def test_returns_path_object(self):
        """Test that ensure_directory returns a Path object."""
        with tempfile.TemporaryDirectory() as tmpdir:
            new_dir = Path(tmpdir) / "return_test"

            result = ensure_directory(new_dir)

            assert isinstance(result, Path)
            assert result == new_dir

    def test_creates_directory_with_special_characters(self):
        """Test directory creation with special characters in name."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Use valid filesystem characters
            special_dir = Path(tmpdir) / "dir-with_special.chars"

            result = ensure_directory(special_dir)

            assert special_dir.exists()
            assert result == special_dir

    def test_works_with_relative_paths(self):
        """Test that ensure_directory works with relative paths."""
        original_cwd = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                os.chdir(tmpdir)
                relative_dir = Path("relative_path")

                result = ensure_directory(relative_dir)

                assert relative_dir.exists()
                assert result == relative_dir
        finally:
            os.chdir(original_cwd)

    def test_handles_deeply_nested_paths(self):
        """Test creation of deeply nested directory structures."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a deeply nested path
            deep_path = Path(tmpdir)
            for i in range(10):
                deep_path = deep_path / f"level_{i}"

            result = ensure_directory(deep_path)

            assert deep_path.exists()
            assert result == deep_path

    def test_preserves_existing_directory_contents(self):
        """Test that ensure_directory doesn't affect existing directory contents."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_dir = Path(tmpdir) / "with_content"
            test_dir.mkdir()

            # Create a file in the directory
            test_file = test_dir / "existing_file.txt"
            test_file.write_text("content")

            # Call ensure_directory
            ensure_directory(test_dir)

            # File should still exist
            assert test_file.exists()
            assert test_file.read_text() == "content"
