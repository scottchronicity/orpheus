"""
Tests for data root path utilities.

Tests the get_data_root() and get_data_path() functions.
"""

import os
from pathlib import Path
from unittest.mock import patch

from orpheus_common.storage.paths import get_data_path, get_data_root


class TestGetDataRoot:
    """Test the get_data_root function."""

    def test_returns_path_object(self):
        """Test that get_data_root returns a Path object."""
        root = get_data_root()
        assert isinstance(root, Path)

    def test_default_path_is_data_orpheus(self):
        """Test that default path is /data/orpheus."""
        with patch.dict(os.environ, {}, clear=True):
            # Clear ORPHEUS_DATA_ROOT if it exists
            os.environ.pop("ORPHEUS_DATA_ROOT", None)
            root = get_data_root()

            assert str(root) == "/data/orpheus"

    def test_respects_orpheus_data_root_env(self):
        """Test that ORPHEUS_DATA_ROOT environment variable is used."""
        with patch.dict(os.environ, {"ORPHEUS_DATA_ROOT": "/custom/path"}):
            root = get_data_root()

            assert str(root) == "/custom/path"

    def test_handles_relative_env_path(self):
        """Test handling of relative path in environment variable."""
        with patch.dict(os.environ, {"ORPHEUS_DATA_ROOT": "relative/path"}):
            root = get_data_root()

            assert str(root) == "relative/path"

    def test_handles_path_with_trailing_slash(self):
        """Test handling of path with trailing slash."""
        with patch.dict(os.environ, {"ORPHEUS_DATA_ROOT": "/custom/path/"}):
            root = get_data_root()

            # Path should normalize trailing slash
            assert "custom" in str(root)
            assert "path" in str(root)

    def test_consistent_return_value(self):
        """Test that multiple calls return same value."""
        root1 = get_data_root()
        root2 = get_data_root()

        assert root1 == root2


class TestGetDataPath:
    """Test the get_data_path function."""

    def test_returns_path_object(self):
        """Test that get_data_path returns a Path object."""
        path = get_data_path("subdir")
        assert isinstance(path, Path)

    def test_single_component(self):
        """Test with single path component."""
        path = get_data_path("audio")

        assert "audio" in str(path)
        assert str(path).startswith(str(get_data_root()))

    def test_multiple_components(self):
        """Test with multiple path components."""
        path = get_data_path("audio", "raw", "2025-11-28")

        path_str = str(path)
        assert "audio" in path_str
        assert "raw" in path_str
        assert "2025-11-28" in path_str

    def test_respects_data_root(self):
        """Test that path is under data root."""
        with patch.dict(os.environ, {"ORPHEUS_DATA_ROOT": "/custom/root"}):
            path = get_data_path("test", "subdir")

            assert str(path).startswith("/custom/root")

    def test_empty_components_handled(self):
        """Test handling of no components."""
        path = get_data_path()

        # Should return just the data root
        assert path == get_data_root()

    def test_path_construction_order(self):
        """Test that path components are in correct order."""
        path = get_data_path("first", "second", "third")

        parts = Path(path).parts
        # Should have data root + components in order
        assert "first" in parts
        assert "second" in parts
        assert "third" in parts

        # Components should be in order
        first_idx = parts.index("first")
        second_idx = parts.index("second")
        third_idx = parts.index("third")

        assert first_idx < second_idx < third_idx

    def test_special_characters_in_components(self):
        """Test path components with special characters."""
        path = get_data_path("audio-files", "channel_1", "2025-11-28")

        path_str = str(path)
        assert "audio-files" in path_str
        assert "channel_1" in path_str
        assert "2025-11-28" in path_str

    def test_consistent_with_manual_construction(self):
        """Test that get_data_path matches manual path construction."""
        auto_path = get_data_path("audio", "raw")
        manual_path = get_data_root() / "audio" / "raw"

        assert auto_path == manual_path
