"""Tests for configuration loading."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from orpheus_agent_video_snapshotter.config import load_app_config


@pytest.fixture
def mock_orpheus_config():
    """Mock OrpheusConfig for testing."""
    with patch("orpheus_agent_video_snapshotter.config.OrpheusConfig") as mock:
        config_instance = MagicMock()

        # Mock storage settings
        config_instance.storage.base_path = "/tmp/test-storage"

        # Mock logging settings
        config_instance.logging.level = "INFO"
        config_instance.logging.format = "text"

        # Mock camera registry
        camera_registry = MagicMock()

        # Create mock cameras with snapshot settings
        mock_camera_1 = MagicMock()
        mock_camera_1.name = "test-camera-1"
        mock_camera_1.enabled = True
        mock_camera_1.snapshots = MagicMock()
        mock_camera_1.snapshots.interval = "5m"
        mock_camera_1.get_rtsp_url.return_value = "rtsp://192.168.1.100/cam/realmonitor"

        mock_camera_2 = MagicMock()
        mock_camera_2.name = "test-camera-2"
        mock_camera_2.enabled = True
        mock_camera_2.snapshots = MagicMock()
        mock_camera_2.snapshots.interval = "10m"
        mock_camera_2.get_rtsp_url.return_value = "rtsp://192.168.1.101/cam/realmonitor"

        # Camera with disabled snapshots
        mock_camera_3 = MagicMock()
        mock_camera_3.name = "disabled-snapshots"
        mock_camera_3.enabled = True
        mock_camera_3.snapshots = MagicMock()
        mock_camera_3.snapshots.interval = "0"
        mock_camera_3.get_rtsp_url.return_value = "rtsp://192.168.1.102/cam/realmonitor"

        # Camera with no snapshots config
        mock_camera_4 = MagicMock()
        mock_camera_4.name = "no-snapshots"
        mock_camera_4.enabled = True
        mock_camera_4.snapshots = None
        mock_camera_4.get_rtsp_url.return_value = "rtsp://192.168.1.103/cam/realmonitor"

        camera_registry.list_cameras.return_value = [
            mock_camera_1,
            mock_camera_2,
            mock_camera_3,
            mock_camera_4,
        ]

        config_instance.camera_registry.return_value = camera_registry
        mock.get_instance.return_value = config_instance
        mock.load.return_value = config_instance

        yield mock


def test_load_config_from_singleton(mock_orpheus_config):
    """Test loading config using singleton instance."""
    config = load_app_config()

    assert config is not None
    assert len(config.cameras) == 2  # Only enabled cameras with valid intervals
    assert config.storage_base_path == Path("/tmp/test-storage")
    assert config.log_level == "INFO"
    assert config.use_json_logging is False


def test_load_config_filters_disabled_snapshots(mock_orpheus_config):
    """Test that cameras with interval='0' are filtered out."""
    config = load_app_config()

    camera_names = [cam.name for cam in config.cameras]
    assert "test-camera-1" in camera_names
    assert "test-camera-2" in camera_names
    assert "disabled-snapshots" not in camera_names
    assert "no-snapshots" not in camera_names


def test_load_config_includes_rtsp_urls(mock_orpheus_config):
    """Test that RTSP URLs are included in camera config."""
    config = load_app_config()

    for camera in config.cameras:
        assert camera.rtsp_url is not None
        assert camera.rtsp_url.startswith("rtsp://")


def test_load_config_parses_intervals(mock_orpheus_config):
    """Test that snapshot intervals are correctly loaded."""
    config = load_app_config()

    camera_by_name = {cam.name: cam for cam in config.cameras}

    assert camera_by_name["test-camera-1"].interval == "5m"
    assert camera_by_name["test-camera-2"].interval == "10m"


def test_load_config_with_json_logging(mock_orpheus_config):
    """Test that JSON logging format is correctly detected."""
    mock_instance = mock_orpheus_config.get_instance.return_value
    mock_instance.logging.format = "json"

    config = load_app_config()

    assert config.use_json_logging is True


def test_load_config_from_path(mock_orpheus_config):
    """Test loading config from specific path."""
    test_path = Path("/tmp/test-config.yaml")
    config = load_app_config(config_path=test_path)

    assert config is not None
    mock_orpheus_config.load.assert_called_once_with(config_path=test_path, allow_missing=False)
