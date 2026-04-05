"""Tests for orpheus_common.system.health module."""

import tempfile
from unittest.mock import MagicMock, patch

from orpheus_common.system.health import (
    StorageMetrics,
    SystemHealth,
    SystemMetrics,
    check_service_status,
    get_data_storage_usage,
    get_system_metrics,
)


class TestSystemMetrics:
    """Tests for SystemMetrics dataclass."""

    def test_create_with_values(self) -> None:
        """SystemMetrics should accept all required fields."""
        metrics = SystemMetrics(
            cpu_percent=45.5,
            memory_percent=62.3,
            disk_percent=35.1,
            uptime_seconds=3600,
        )
        assert metrics.cpu_percent == 45.5
        assert metrics.memory_percent == 62.3
        assert metrics.disk_percent == 35.1
        assert metrics.uptime_seconds == 3600

    def test_to_dict(self) -> None:
        """SystemMetrics.to_dict should return all fields."""
        metrics = SystemMetrics(
            cpu_percent=45.5,
            memory_percent=62.3,
            disk_percent=35.1,
            uptime_seconds=3600,
        )
        result = metrics.to_dict()

        assert result["cpu_percent"] == 45.5
        assert result["memory_percent"] == 62.3
        assert result["disk_percent"] == 35.1
        assert result["uptime_seconds"] == 3600


class TestStorageMetrics:
    """Tests for StorageMetrics dataclass."""

    def test_create_ok_metrics(self) -> None:
        """StorageMetrics should store OK metrics."""
        metrics = StorageMetrics(
            ok=True,
            path="/data/orpheus",
            total=1000000000,
            used=250000000,
            free=750000000,
            percent=25.0,
        )
        assert metrics.ok is True
        assert metrics.path == "/data/orpheus"
        assert metrics.total == 1000000000
        assert metrics.percent == 25.0

    def test_create_error_metrics(self) -> None:
        """StorageMetrics should store error state."""
        metrics = StorageMetrics(
            ok=False,
            path="/missing/path",
            total=0,
            used=0,
            free=0,
            percent=0.0,
            error="Path not found",
        )
        assert metrics.ok is False
        assert metrics.error == "Path not found"

    def test_to_dict_ok(self) -> None:
        """StorageMetrics.to_dict should include usage when OK."""
        metrics = StorageMetrics(
            ok=True,
            path="/data",
            total=1000,
            used=250,
            free=750,
            percent=25.0,
        )
        result = metrics.to_dict()

        assert result["ok"] is True
        assert result["path"] == "/data"
        assert result["total"] == 1000
        assert result["used"] == 250
        assert result["free"] == 750
        assert result["percent"] == 25.0

    def test_to_dict_error(self) -> None:
        """StorageMetrics.to_dict should include error when not OK."""
        metrics = StorageMetrics(
            ok=False,
            path="/missing",
            total=0,
            used=0,
            free=0,
            percent=0.0,
            error="Not found",
        )
        result = metrics.to_dict()

        assert result["ok"] is False
        assert result["path"] == "/missing"
        assert result["error"] == "Not found"
        assert "total" not in result


class TestSystemHealth:
    """Tests for SystemHealth class."""

    def test_get_metrics_returns_system_metrics(self) -> None:
        """SystemHealth.get_metrics should return SystemMetrics."""
        health = SystemHealth()
        metrics = health.get_metrics()

        assert isinstance(metrics, SystemMetrics)
        assert 0 <= metrics.cpu_percent <= 100
        assert 0 <= metrics.memory_percent <= 100
        assert 0 <= metrics.disk_percent <= 100
        assert metrics.uptime_seconds >= 0

    def test_get_data_storage_existing_path(self) -> None:
        """SystemHealth.get_data_storage should handle existing paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict("os.environ", {"ORPHEUS_DATA_ROOT": tmpdir}):
                health = SystemHealth()
                metrics = health.get_data_storage()

                assert isinstance(metrics, StorageMetrics)
                assert metrics.ok is True
                assert metrics.path == tmpdir
                assert metrics.total > 0

    def test_get_data_storage_missing_path(self) -> None:
        """SystemHealth.get_data_storage should handle missing paths."""
        import uuid

        nonexistent_path = f"/tmp/orpheus_test_nonexistent_{uuid.uuid4().hex}"
        with patch.dict("os.environ", {"ORPHEUS_DATA_ROOT": nonexistent_path}):
            health = SystemHealth()
            metrics = health.get_data_storage()

            assert isinstance(metrics, StorageMetrics)
            assert metrics.ok is False
            assert "not found" in metrics.error.lower()

    def test_get_data_storage_uses_default(self) -> None:
        """SystemHealth.get_data_storage should use default path when env not set."""
        # Clear the env var but expect default handling
        with patch.dict("os.environ", {}, clear=False):
            # Remove ORPHEUS_DATA_ROOT if it exists
            import os

            original = os.environ.pop("ORPHEUS_DATA_ROOT", None)
            try:
                health = SystemHealth()
                metrics = health.get_data_storage()
                # Default path is /data/orpheus which may not exist
                assert metrics.path == "/data/orpheus"
            finally:
                if original:
                    os.environ["ORPHEUS_DATA_ROOT"] = original

    def test_check_service_no_systemctl(self) -> None:
        """SystemHealth.check_service should handle missing systemctl."""
        with patch("shutil.which", return_value=None):
            with patch("os.path.exists", return_value=False):
                health = SystemHealth()
                result = health.check_service("orpheus-test")

                assert result["name"] == "orpheus-test"
                assert result["status"] == "unknown"
                assert "systemctl not available" in result["reason"]

    def test_check_service_running(self) -> None:
        """SystemHealth.check_service should detect running services."""
        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("shutil.which", return_value="/bin/systemctl"):
            with patch("subprocess.run", return_value=mock_result):
                health = SystemHealth()
                result = health.check_service("test-service")

                assert result["name"] == "test-service"
                assert result["status"] == "running"
                assert result["reason"] == ""

    def test_check_service_stopped(self) -> None:
        """SystemHealth.check_service should detect stopped services."""
        mock_result = MagicMock()
        mock_result.returncode = 1

        with patch("shutil.which", return_value="/bin/systemctl"):
            with patch("subprocess.run", return_value=mock_result):
                health = SystemHealth()
                result = health.check_service("stopped-service")

                assert result["name"] == "stopped-service"
                assert result["status"] == "stopped"

    def test_check_service_timeout(self) -> None:
        """SystemHealth.check_service should handle timeouts."""
        import subprocess

        with patch("shutil.which", return_value="/bin/systemctl"):
            with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="", timeout=2)):
                health = SystemHealth()
                result = health.check_service("slow-service")

                assert result["status"] == "unknown"
                assert "timeout" in result["reason"].lower()

    def test_check_services_multiple(self) -> None:
        """SystemHealth.check_services should check multiple services."""
        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("shutil.which", return_value="/bin/systemctl"):
            with patch("subprocess.run", return_value=mock_result):
                health = SystemHealth()
                results = health.check_services(["svc1", "svc2", "svc3"])

                assert len(results) == 3
                assert results[0]["name"] == "svc1"
                assert results[1]["name"] == "svc2"
                assert results[2]["name"] == "svc3"


class TestConvenienceFunctions:
    """Tests for convenience functions."""

    def test_get_system_metrics(self) -> None:
        """get_system_metrics should return dictionary."""
        result = get_system_metrics()

        assert isinstance(result, dict)
        assert "cpu_percent" in result
        assert "memory_percent" in result
        assert "disk_percent" in result
        assert "uptime_seconds" in result

    def test_get_data_storage_usage(self) -> None:
        """get_data_storage_usage should return dictionary."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict("os.environ", {"ORPHEUS_DATA_ROOT": tmpdir}):
                result = get_data_storage_usage()

                assert isinstance(result, dict)
                assert "ok" in result
                assert "path" in result

    def test_check_service_status(self) -> None:
        """check_service_status should return dictionary."""
        with patch("shutil.which", return_value=None):
            with patch("os.path.exists", return_value=False):
                result = check_service_status("test-svc")

                assert isinstance(result, dict)
                assert "name" in result
                assert "status" in result
                assert "reason" in result
