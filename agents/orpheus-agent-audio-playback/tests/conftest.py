"""Pytest configuration and fixtures for audio playback agent tests."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_orpheus_config():
    """Mock OrpheusConfig for testing."""
    with patch("orpheus_agent_audio_playback.main.OrpheusConfig") as mock_config:
        mock_instance = MagicMock()
        mock_instance.mqtt.broker_host = "localhost"
        mock_instance.mqtt.broker_port = 1883
        mock_instance.mqtt.keepalive = 60
        mock_instance.logging.level = "INFO"
        mock_config.get_instance.return_value = mock_instance
        mock_config.load.return_value = mock_instance
        yield mock_config


@pytest.fixture
def mock_mqtt_client():
    """Mock MQTT client for testing."""
    with patch("orpheus_agent_audio_playback.main.MQTTClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client.connect = MagicMock()
        mock_client.disconnect = MagicMock()
        mock_client.subscribe = MagicMock()
        mock_client.publish = MagicMock()
        mock_client_class.return_value = mock_client
        yield mock_client


@pytest.fixture
def mock_sound_registry():
    """Mock sound registry for testing."""
    with patch("orpheus_agent_audio_playback.main.get_sound_registry") as mock_registry_func:
        mock_registry = MagicMock()
        mock_registry.list_sounds.return_value = ["test_tone_1", "test_beep", "test_silence"]
        mock_registry.get_sound_path.return_value = Path("/fake/path/test_tone_1.wav")
        mock_registry_func.return_value = mock_registry
        yield mock_registry


@pytest.fixture
def mock_audio_player():
    """Mock audio player for testing."""
    with patch("orpheus_agent_audio_playback.main.get_audio_player") as mock_player_func:
        mock_player = AsyncMock()
        mock_player.play = AsyncMock()
        mock_player.stop = AsyncMock()
        mock_player.is_playing.return_value = False
        mock_player_func.return_value = mock_player
        yield mock_player


@pytest.fixture
def test_audio_file(tmp_path: Path) -> Path:
    """Create a temporary test audio file."""
    audio_file = tmp_path / "test.wav"
    audio_file.write_text("fake audio data")
    return audio_file
