"""Test fixtures for video timelapser agent tests."""

from pathlib import Path

import pytest


@pytest.fixture
def mock_config_path(tmp_path: Path) -> Path:
    """Create a minimal test configuration file."""
    config_content = """
mqtt:
  broker_host: "localhost"
  broker_port: 1883
  keepalive: 60

cameras:
  auth:
    username: "test"
    password: "test"
  test-camera-1:
    type: "amcrest"
    host: "192.168.1.100"
    model: "IP5M-B1186EW-AI-V3"
    enabled: true
    timelapses:
      - label: "daily"
        start_time: "06:00"
        lookback_window: "24h"
        sampling_interval: "15m"
        retention_days: 90
        clip_duration: 2.0
      - label: "long-view"
        start_time: "18:00"
        lookback_window: "48h"
        sampling_interval: "30m"
        retention_days: 90
        clip_duration: 1.0
  test-camera-2:
    type: "amcrest"
    host: "192.168.1.101"
    model: "IP5M-B1186EW-AI-V3"
    enabled: true
    timelapses:
      - label: "daily"
        start_time: "12:00"
        lookback_window: "24h"
        sampling_interval: "15m"
        retention_days: 90
        clip_duration: 2.0
  disabled-camera:
    type: "amcrest"
    host: "192.168.1.102"
    model: "IP5M-B1186EW-AI-V3"
    enabled: false
    timelapses:
      - label: "daily"
        start_time: "06:00"
        lookback_window: "24h"
        sampling_interval: "15m"
        retention_days: 90
        clip_duration: 2.0
  no-timelapse-camera:
    type: "amcrest"
    host: "192.168.1.103"
    model: "IP5M-B1186EW-AI-V3"
    enabled: true

storage:
  base_path: "/tmp/test-storage"

logging:
  level: "INFO"
  format: "text"
"""
    config_file = tmp_path / "orpheus.yaml"
    config_file.write_text(config_content)
    return config_file


@pytest.fixture
def mock_storage_path(tmp_path: Path) -> Path:
    """Create a temporary storage directory."""
    storage = tmp_path / "storage"
    storage.mkdir(parents=True, exist_ok=True)
    return storage
