"""Test configuration and fixtures for orpheus_ui tests."""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


@pytest.fixture
def mock_config():
    """Mock OrpheusConfig for testing."""
    mock_config_instance = MagicMock()
    mock_config_instance.mqtt.broker_host = "localhost"
    mock_config_instance.mqtt.broker_port = 1883
    mock_config_instance.mqtt.keepalive = 60
    mock_config_instance.config_source.return_value = "test"
    mock_config_instance.dashboard_poll_interval.return_value = 5000
    mock_config_instance.dashboard_services.return_value = [
        "orpheus-mqtt",
        "orpheus-ui",
        "orpheus-agent-audio-motion",
    ]
    mock_config_instance.camera_registry.return_value = []

    with patch("orpheus_common.OrpheusConfig.get_instance", return_value=mock_config_instance):
        yield mock_config_instance
