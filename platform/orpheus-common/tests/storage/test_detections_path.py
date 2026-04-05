"""
Tests for detection database path utilities.

Tests the get_detections_path() function for database file paths.
"""

import os
from pathlib import Path
from unittest.mock import patch

from orpheus_common.storage.paths import get_detections_path


class TestGetDetectionsPath:
    """Test the get_detections_path function."""

    def test_default_database_name(self):
        """Test default database filename."""
        path = get_detections_path()

        assert isinstance(path, Path)
        assert str(path).endswith("detections/orpheus.db")

    def test_custom_database_name(self):
        """Test custom database filename."""
        path = get_detections_path("custom.db")

        assert isinstance(path, Path)
        assert str(path).endswith("detections/custom.db")

    def test_respects_data_root_env(self):
        """Test that ORPHEUS_DATA_ROOT is respected."""
        with patch.dict(os.environ, {"ORPHEUS_DATA_ROOT": "/custom/root"}):
            path = get_detections_path()

            assert str(path).startswith("/custom/root")
            assert str(path).endswith("detections/orpheus.db")

    def test_backup_database_path(self):
        """Test path for backup database."""
        path = get_detections_path("backup_2025_11_28.db")

        assert isinstance(path, Path)
        assert str(path).endswith("detections/backup_2025_11_28.db")

    def test_different_filenames_give_different_paths(self):
        """Test that different filenames produce different paths."""
        path1 = get_detections_path("db1.db")
        path2 = get_detections_path("db2.db")

        assert path1 != path2
        assert str(path1).endswith("db1.db")
        assert str(path2).endswith("db2.db")

    def test_path_structure(self):
        """Test that path follows expected structure."""
        path = get_detections_path()

        path_parts = Path(path).parts
        assert "detections" in path_parts
        assert path_parts[-1] == "orpheus.db"

    def test_non_db_extension(self):
        """Test that function works with non-.db files."""
        path = get_detections_path("export.json")

        assert isinstance(path, Path)
        assert str(path).endswith("detections/export.json")

    def test_empty_filename_edge_case(self):
        """Test behavior with empty filename."""
        path = get_detections_path("")

        assert isinstance(path, Path)
        # Should still have detections directory
        assert "detections" in str(path)
