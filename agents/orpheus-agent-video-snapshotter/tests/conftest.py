"""Test fixtures for video snapshotter agent tests."""

from pathlib import Path

import pytest
from orpheus_common.config import OrpheusConfig


@pytest.fixture(autouse=True)
def reset_orpheus_config_singleton() -> None:
    """Reset OrpheusConfig singleton between tests.

    Prevents cross-test config pollution. See
    docs/agent-instructions/99-gotchas.md.
    """
    original_instance = OrpheusConfig._instance
    original_dotenv = OrpheusConfig._DOTENV_LOADED
    OrpheusConfig._instance = None
    OrpheusConfig._DOTENV_LOADED = False
    yield
    OrpheusConfig._instance = original_instance
    OrpheusConfig._DOTENV_LOADED = original_dotenv


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
    snapshots:
      interval: "5m"
  test-camera-2:
    type: "amcrest"
    host: "192.168.1.101"
    model: "IP5M-B1186EW-AI-V3"
    enabled: true
    snapshots:
      interval: "10m"
  disabled-camera:
    type: "amcrest"
    host: "192.168.1.102"
    model: "IP5M-B1186EW-AI-V3"
    enabled: false
    snapshots:
      interval: "5m"

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
