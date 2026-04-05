"""Tests for configuration loading."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from orpheus_agent_video_timelapser.config import load_app_config


@pytest.fixture
def mock_orpheus_config():
    """Mock OrpheusConfig for testing."""
    with patch("orpheus_agent_video_timelapser.config.OrpheusConfig") as mock:
        config_instance = MagicMock()

        # Mock storage settings
        config_instance.storage.base_path = "/tmp/test-storage"

        # Mock logging settings
        config_instance.logging.level = "INFO"
        config_instance.logging.format = "text"

        # Mock camera registry
        camera_registry = MagicMock()

        # Create mock TimelapseConfig objects
        mock_tl_1 = MagicMock()
        mock_tl_1.start_time = "06:00"
        mock_tl_1.lookback_window = "24h"
        mock_tl_1.sampling_interval = "15m"
        mock_tl_1.retention_days = 90
        mock_tl_1.clip_duration = 2.0

        mock_tl_2 = MagicMock()
        mock_tl_2.start_time = "18:00"
        mock_tl_2.lookback_window = "48h"
        mock_tl_2.sampling_interval = "30m"
        mock_tl_2.retention_days = 90
        mock_tl_2.clip_duration = 1.0

        # Create mock cameras with timelapse settings
        mock_camera_1 = MagicMock()
        mock_camera_1.name = "test-camera-1"
        mock_camera_1.enabled = True
        mock_camera_1.timelapses = [mock_tl_1, mock_tl_2]

        mock_camera_2 = MagicMock()
        mock_camera_2.name = "test-camera-2"
        mock_camera_2.enabled = True
        mock_tl_3 = MagicMock()
        mock_tl_3.start_time = "12:00"
        mock_tl_3.lookback_window = "24h"
        mock_tl_3.sampling_interval = "15m"
        mock_tl_3.retention_days = 90
        mock_tl_3.clip_duration = 2.0
        mock_camera_2.timelapses = [mock_tl_3]

        # Camera with no timelapses
        mock_camera_3 = MagicMock()
        mock_camera_3.name = "no-timelapses"
        mock_camera_3.enabled = True
        mock_camera_3.timelapses = None

        # Camera with empty timelapses list
        mock_camera_4 = MagicMock()
        mock_camera_4.name = "empty-timelapses"
        mock_camera_4.enabled = True
        mock_camera_4.timelapses = []

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
    assert len(config.cameras) == 2  # Only cameras with timelapses
    assert config.storage_base_path == Path("/tmp/test-storage")
    assert config.log_level == "INFO"
    assert config.use_json_logging is False


def test_load_config_filters_no_timelapses(mock_orpheus_config):
    """Test that cameras without timelapses are filtered out."""
    config = load_app_config()

    camera_names = [cam.name for cam in config.cameras]
    assert "test-camera-1" in camera_names
    assert "test-camera-2" in camera_names
    assert "no-timelapses" not in camera_names
    assert "empty-timelapses" not in camera_names


def test_load_config_includes_timelapse_settings(mock_orpheus_config):
    """Test that timelapse settings are included in camera config."""
    config = load_app_config()

    camera_by_name = {cam.name: cam for cam in config.cameras}

    # Check camera-1 has 2 timelapse configs
    assert len(camera_by_name["test-camera-1"].timelapses) == 2
    assert camera_by_name["test-camera-1"].timelapses[0].start_time == "06:00"
    assert camera_by_name["test-camera-1"].timelapses[0].lookback_window == "24h"
    assert camera_by_name["test-camera-1"].timelapses[0].sampling_interval == "15m"
    assert camera_by_name["test-camera-1"].timelapses[1].start_time == "18:00"

    # Check camera-2 has 1 timelapse config
    assert len(camera_by_name["test-camera-2"].timelapses) == 1
    assert camera_by_name["test-camera-2"].timelapses[0].start_time == "12:00"


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
