"""
Tests for storage hardware monitoring.

Tests the get_storage_hardware_info() function that returns storage
device information including mount status, writability, and usage.
"""

import os
import tempfile
from unittest.mock import patch

from orpheus_common.hardware.storage import (
    _get_single_storage_info,
    get_storage_hardware_info,
)


class TestGetSingleStorageInfo:
    """Test the internal _get_single_storage_info helper."""

    def test_nonexistent_path(self):
        """Test handling of non-existent path."""
        info = _get_single_storage_info("Test", "/nonexistent/path/xyz")

        assert info["name"] == "Test"
        assert info["path"] == "/nonexistent/path/xyz"
        assert info["exists"] is False
        assert info["status"] == "critical"
        assert "Path not found" in info["message"]

    def test_existing_writable_directory(self):
        """Test handling of existing writable directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            info = _get_single_storage_info("Test", tmpdir, check_writable=True)

            assert info["exists"] is True
            assert info["checks"]["path_exists"] is True
            assert info["checks"]["writable"] is True
            assert info["status"] in ["healthy", "degraded"]  # May vary by mount status
            assert info["usage"] is not None
            assert "total" in info["usage"]
            assert "used" in info["usage"]
            assert "free" in info["usage"]
            assert "percent" in info["usage"]

    def test_no_writability_check(self):
        """Test when writability check is disabled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Mock disk_usage to return low usage (<85%)
            with patch("shutil.disk_usage") as mock_usage:
                mock_usage.return_value = type(
                    "obj", (object,), {"total": 100, "used": 10, "free": 90}
                )()
                info = _get_single_storage_info("Test", tmpdir, check_writable=False)

                assert info["exists"] is True
                assert info["checks"]["path_exists"] is True
                assert "writable" not in info["checks"]
                assert info["status"] == "healthy"

    def test_usage_threshold_90_percent(self):
        """Test that >90% usage triggers critical status."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Mock disk_usage to return >90% used
            with patch("shutil.disk_usage") as mock_usage:
                mock_usage.return_value = type(
                    "obj", (object,), {"total": 100, "used": 95, "free": 5}
                )()

                info = _get_single_storage_info("Test", tmpdir, check_writable=True)

                assert info["usage"]["percent"] == 95.0
                assert info["status"] == "critical"
                assert "Storage full" in info["message"]

    def test_usage_threshold_85_percent(self):
        """Test that >85% usage triggers degraded status."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Mock disk_usage to return >85% used
            with patch("shutil.disk_usage") as mock_usage:
                mock_usage.return_value = type(
                    "obj", (object,), {"total": 100, "used": 87, "free": 13}
                )()

                info = _get_single_storage_info("Test", tmpdir, check_writable=True)

                assert info["usage"]["percent"] == 87.0
                assert info["status"] == "degraded"
                assert "filling up" in info["message"]

    def test_required_mount_not_mounted(self):
        """Test degraded status when mount is required but not present."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Mock disk_usage to return low usage (<85%)
            with patch("shutil.disk_usage") as mock_usage:
                mock_usage.return_value = type(
                    "obj", (object,), {"total": 100, "used": 10, "free": 90}
                )()
                # Most temp dirs are not mount points
                info = _get_single_storage_info("Test", tmpdir, required_mount=True)

                if not info["is_mount"]:
                    assert info["status"] == "degraded"
                    assert "Not mounted" in info["message"]


class TestGetStorageHardwareInfo:
    """Test the main get_storage_hardware_info() function."""

    def test_returns_list_of_devices(self):
        """Test that function returns a list of storage devices."""
        devices = get_storage_hardware_info()

        assert isinstance(devices, list)
        assert len(devices) == 2  # Root + external storage

    def test_includes_root_filesystem(self):
        """Test that root filesystem is included."""
        devices = get_storage_hardware_info()

        root_device = next((d for d in devices if d["name"] == "Root Filesystem"), None)
        assert root_device is not None
        assert root_device["path"] == "/"
        assert root_device["exists"] is True

    def test_includes_external_storage(self):
        """Test that external storage is included."""
        devices = get_storage_hardware_info()

        external_device = next((d for d in devices if "External Storage" in d["name"]), None)
        assert external_device is not None
        # Default path is /data/orpheus
        assert "/data/orpheus" in external_device["path"] or external_device[
            "path"
        ] == os.environ.get("ORPHEUS_DATA_ROOT", "/data/orpheus")

    def test_respects_orpheus_data_root_env(self):
        """Test that ORPHEUS_DATA_ROOT environment variable is respected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"ORPHEUS_DATA_ROOT": tmpdir}):
                devices = get_storage_hardware_info()

                external_device = next(
                    (d for d in devices if "External Storage" in d["name"]), None
                )
                assert external_device is not None
                assert external_device["path"] == tmpdir

    def test_all_devices_have_required_fields(self):
        """Test that all devices have the required fields."""
        devices = get_storage_hardware_info()

        required_fields = [
            "name",
            "path",
            "exists",
            "is_mount",
            "filesystem",
            "device",
            "status",
            "checks",
        ]

        for device in devices:
            for field in required_fields:
                assert field in device, f"Device {device['name']} missing field {field}"

    def test_root_filesystem_not_writable_check(self):
        """Test that root filesystem doesn't perform writability check."""
        devices = get_storage_hardware_info()

        root_device = next((d for d in devices if d["name"] == "Root Filesystem"), None)
        assert root_device is not None
        # Root should not have writable check since it's read-only on macOS
        assert "writable" not in root_device["checks"]

    def test_external_storage_has_writable_check(self):
        """Test that external storage performs writability check."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"ORPHEUS_DATA_ROOT": tmpdir}):
                devices = get_storage_hardware_info()

                external_device = next(
                    (d for d in devices if "External Storage" in d["name"]), None
                )
                assert external_device is not None
                assert "writable" in external_device["checks"]

    def test_nonexistent_external_storage_marked_critical(self):
        """Test that non-existent external storage is marked as critical."""
        with patch.dict(os.environ, {"ORPHEUS_DATA_ROOT": "/nonexistent/path/xyz"}):
            devices = get_storage_hardware_info()

            external_device = next((d for d in devices if "External Storage" in d["name"]), None)
            assert external_device is not None
            assert external_device["status"] == "critical"
            assert external_device["exists"] is False

    def test_usage_statistics_present(self):
        """Test that usage statistics are present for existing paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"ORPHEUS_DATA_ROOT": tmpdir}):
                devices = get_storage_hardware_info()

                external_device = next(
                    (d for d in devices if "External Storage" in d["name"]), None
                )
                assert external_device is not None
                assert external_device["usage"] is not None
                assert "total" in external_device["usage"]
                assert "used" in external_device["usage"]
                assert "free" in external_device["usage"]
                assert "percent" in external_device["usage"]
                assert isinstance(external_device["usage"]["percent"], float)
