"""Test configuration and fixtures for orpheus_ui tests."""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# Import after sys.path is set up so we get the local orpheus_common.
from orpheus_common.config import OrpheusConfig  # noqa: E402


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
def mock_config(tmp_path):
    """Mock OrpheusConfig for testing."""
    mock_config_instance = MagicMock()
    mock_config_instance.mqtt.broker_host = "localhost"
    mock_config_instance.mqtt.broker_port = 1883
    mock_config_instance.mqtt.keepalive = 60
    # A REAL, writable base_path: anything that resolves the data root (the
    # login rate-limiter's SQLite ledger, storage helpers) gets a usable dir
    # instead of a MagicMock path that raises OperationalError on open.
    mock_config_instance.storage.base_path = str(tmp_path)
    mock_config_instance.config_source.return_value = "test"
    mock_config_instance.dashboard_poll_interval.return_value = 5000
    mock_config_instance.dashboard_services.return_value = [
        "orpheus-backplane",
        "orpheus-ui",
        "orpheus-agent-audio-motion",
    ]
    mock_config_instance.camera_registry.return_value = []

    with patch("orpheus_common.OrpheusConfig.get_instance", return_value=mock_config_instance):
        yield mock_config_instance
