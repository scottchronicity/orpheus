"""Test fixtures for video motion agent tests."""

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
  topics:
    video_motion_events: "orpheus/video/motion/events"
    video_motion_status: "orpheus/video/motion/status"

cameras:
  auth:
    username: "test"
    password: "test"
  motion_detection:
    fps: 10
    width: 640
    height: 480
    algorithm: "background_subtraction"
    motion_threshold: 25.0
    release_threshold: 12.5
    holdoff_seconds: 2.0
    min_duration_seconds: 0.5
    max_duration_seconds: 30.0
    prebuffer_seconds: 1.0
  test-camera:
    type: "amcrest"
    host: "192.168.1.100"
    model: "IP5M-B1186EW-AI-V3"
    enabled: true

storage:
  base_path: "/tmp/test-storage"
  format:
    video: "mp4"
  retention:
    raw_video_days: 30

logging:
  level: "INFO"
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
"""
    config_file = tmp_path / "orpheus.yaml"
    config_file.write_text(config_content)
    return config_file
