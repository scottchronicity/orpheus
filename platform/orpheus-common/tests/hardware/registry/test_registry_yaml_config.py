from pathlib import Path
from unittest.mock import patch

from orpheus_common.hardware.cameras.amcrest import AmcrestCamera
from orpheus_common.hardware.registry import CameraRegistry


def test_from_config_loads_yaml_fixture():
    fixture_path = Path(__file__).parent / "fixtures" / "cameras_test.yaml"
    cameras_data = {
        "auth": {"username": "admin", "password": "testpass123"},
        "north": {
            "type": "amcrest",
            "host": "192.168.1.100",
            "model": "IP5M-B1186EW-AI-V3",
            "enabled": True,
        },
        "south": {
            "type": "amcrest",
            "host": "192.168.1.101",
            "model": "IP5M-B1186EW-AI-V3",
            "enabled": False,
        },
    }
    with patch("orpheus_common.config.Config.load") as mock_load:
        mock_config = mock_load.return_value
        mock_config.get.return_value = cameras_data
        registry = CameraRegistry.from_config(str(fixture_path.resolve()))

    assert len(registry) == 1
    camera = registry.get("north")
    assert camera is not None
    assert registry.get("south") is None

    assert camera.name == "north"
    assert camera.host == "192.168.1.100"
    assert isinstance(camera, AmcrestCamera)
    assert camera.username == "admin"
    assert camera.password == "testpass123"


def test_from_config_loads_cameras_with_snapshots_and_timelapses():
    """Test that cameras loaded from config have snapshots and timelapses attributes."""
    fixture_path = Path(__file__).parent / "fixtures" / "cameras_test.yaml"
    cameras_data = {
        "auth": {"username": "admin", "password": "testpass123"},
        "north": {
            "type": "amcrest",
            "host": "192.168.1.100",
            "model": "IP5M-B1186EW-AI-V3",
            "enabled": True,
            "snapshots": {"interval": "30m"},
            "timelapses": [
                {
                    "label": "daily",
                    "start_time": "08:00",
                    "lookback_window": "24h",
                    "sampling_interval": "15m",
                    "retention_days": 90,
                    "clip_duration": 2.0,
                }
            ],
        },
        "south": {
            "type": "amcrest",
            "host": "192.168.1.101",
            "model": "IP5M-B1186EW-AI-V3",
            "enabled": True,
        },
    }
    with patch("orpheus_common.config.Config.load") as mock_load:
        mock_config = mock_load.return_value
        mock_config.get.return_value = cameras_data
        registry = CameraRegistry.from_config(str(fixture_path.resolve()))

    # Check camera with snapshots and timelapses
    north = registry.get("north")
    assert north is not None
    assert hasattr(north, "snapshots"), "Camera should have 'snapshots' attribute"
    assert hasattr(north, "timelapses"), "Camera should have 'timelapses' attribute"
    assert north.snapshots is not None
    assert north.snapshots.interval == "30m"
    assert north.timelapses is not None
    assert len(north.timelapses) == 1
    assert north.timelapses[0].start_time == "08:00"
    assert north.timelapses[0].lookback_window == "24h"
    assert north.timelapses[0].sampling_interval == "15m"
    assert north.timelapses[0].retention_days == 90
    assert north.timelapses[0].clip_duration == 2.0

    # Check camera without snapshots/timelapses
    south = registry.get("south")
    assert south is not None
    assert hasattr(south, "snapshots"), "Camera should have 'snapshots' attribute"
    assert hasattr(south, "timelapses"), "Camera should have 'timelapses' attribute"
    assert south.snapshots is None
    assert south.timelapses is None
