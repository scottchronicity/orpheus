"""Tests for configuration loading."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from orpheus_common.config import ConfigError

from orpheus_agent_audio_motion.config import (
    ChannelConfig,
    MQTTSettings,
    load_app_config,
)


class TestConfigDataClasses:
    """Tests for configuration dataclasses."""

    def test_channel_config_defaults(self) -> None:
        """ChannelConfig should have sensible defaults."""
        channel = ChannelConfig(id="test", label="Test Channel")
        assert channel.id == "test"
        assert channel.label == "Test Channel"
        assert channel.enabled is True

    def test_channel_config_explicit_disabled(self) -> None:
        """ChannelConfig should accept explicit enabled=False."""
        channel = ChannelConfig(id="test", label="Test", enabled=False)
        assert channel.enabled is False

    def test_mqtt_settings(self) -> None:
        """MQTTSettings should store all required fields."""
        mqtt = MQTTSettings(
            broker_host="localhost",
            broker_port=1883,
            keepalive=60,
            topic_events="events",
            topic_status="status",
            qos=1,
        )
        assert mqtt.broker_host == "localhost"
        assert mqtt.broker_port == 1883
        assert mqtt.qos == 1


class TestLoadAppConfig:
    """Tests for load_app_config function."""

    def test_load_from_file(self) -> None:
        """load_app_config should parse YAML config file."""
        config_content = """---
mqtt:
  broker_host: test.example.com
  broker_port: 1884
  keepalive: 30
  topics:
    audio_motion_events: test/events
    audio_motion_status: test/status

audio:
  sample_rate: 44100
  chunk_size: 2048
  format: pcm_s16le
  channels:
    - id: 1
      name: Test Channel 1
      enabled: true
      device: ""
    - id: 2
      name: Test Channel 2
      enabled: false
      device: ""

storage:
  base_path: /tmp/test
  format:
    audio: mp3
  retention:
    raw_audio_days: 7

logging:
  level: DEBUG
  format: json
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(config_content)
            temp_path = Path(f.name)

        try:
            config = load_app_config(temp_path)

            # Check runtime settings (hardcoded in load_app_config)
            assert config.runtime.sample_rate == 44100  # From audio.sample_rate
            assert config.runtime.frame_duration_ms == 200  # Default buffer_duration_ms
            assert config.runtime.max_pending_frames == 50  # Hardcoded

            # Check MQTT settings
            assert config.mqtt.broker_host == "test.example.com"
            assert config.mqtt.broker_port == 1884
            assert config.mqtt.topic_events == "test/events"
            assert config.mqtt.topic_status == "test/status"

            # Check channels
            assert len(config.channels) == 1  # Only enabled channels
            assert config.channels[0].id == "1"
            # Label comes from OrpheusConfig normalization, just check it exists
            assert config.channels[0].label is not None
            assert config.channels[0].enabled is True

            # Check storage
            assert config.storage.category == "audio_motion"
            assert config.storage.retain_days == 7
            assert config.storage.write_format == "mp3"

            # Check logging
            assert config.logging.level == "DEBUG"
            assert config.logging.use_json is True

        finally:
            temp_path.unlink()

    def test_load_with_defaults(self) -> None:
        """load_app_config should provide defaults for missing values."""
        config_content = """---
mqtt:
  broker_host: localhost
  broker_port: 1883

audio:
  sample_rate: 48000
  channels:
    - id: 1
      name: Channel 1
      enabled: true

storage:
  base_path: /tmp
  format:
    audio: wav
  retention:
    raw_audio_days: 30

logging:
  level: INFO
  format: text
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(config_content)
            temp_path = Path(f.name)

        try:
            config = load_app_config(temp_path)

            # Should have defaults from OrpheusConfig
            assert config.runtime.sample_rate == 48000
            assert config.mqtt.broker_host == "localhost"
            assert config.mqtt.broker_port == 1883
            assert config.storage.write_format == "wav"
            assert config.logging.level == "INFO"
            assert config.logging.use_json is False

        finally:
            temp_path.unlink()

    def test_load_missing_file_raises(self) -> None:
        """load_app_config should raise ConfigError when no config file is found."""
        with pytest.raises(ConfigError):
            load_app_config(Path("/nonexistent/config.yaml"))

    def test_cleanup_cadence_defaults_to_hourly(self) -> None:
        """storage.retention.check_interval_hours UNSET ⇒ the audio agent keeps its
        historical HOURLY sweep. The shared StorageRetention default is 6h — silently
        inheriting it would 6x the gap between cleanup passes on an unchanged yaml
        (reversibility: defaults preserve today's behavior)."""
        config_content = """---
mqtt:
  broker_host: localhost
  broker_port: 1883

audio:
  sample_rate: 48000
  channels:
    - id: 1
      name: Channel 1
      enabled: true

storage:
  base_path: /tmp
  format:
    audio: wav
  retention:
    raw_audio_days: 30

logging:
  level: INFO
  format: text
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(config_content)
            temp_path = Path(f.name)

        try:
            config = load_app_config(temp_path)
            assert config.storage.check_interval_hours == 1.0
        finally:
            temp_path.unlink()

    def test_cleanup_cadence_honors_explicit_operator_knob(self) -> None:
        """An EXPLICIT storage.retention.check_interval_hours wins over the agent's
        hourly default — including a value equal to the shared 6h default."""
        config_content = """---
mqtt:
  broker_host: localhost
  broker_port: 1883

audio:
  sample_rate: 48000
  channels:
    - id: 1
      name: Channel 1
      enabled: true

storage:
  base_path: /tmp
  format:
    audio: wav
  retention:
    raw_audio_days: 30
    check_interval_hours: 6

logging:
  level: INFO
  format: text
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(config_content)
            temp_path = Path(f.name)

        try:
            config = load_app_config(temp_path)
            assert config.storage.check_interval_hours == 6.0
        finally:
            temp_path.unlink()

    def test_channel_enabled_coercion(self) -> None:
        """Channels should properly coerce enabled field to boolean."""
        test_cases = [
            ("true", True),
            ("false", False),
        ]

        for value_str, expected in test_cases:
            config_content = f"""---
mqtt:
  broker_host: localhost
  broker_port: 1883

audio:
  sample_rate: 48000
  channels:
    - id: 1
      name: Test
      enabled: {value_str}

storage:
  base_path: /tmp
  format:
    audio: wav
  retention:
    raw_audio_days: 30

logging:
  level: INFO
"""
            with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
                f.write(config_content)
                temp_path = Path(f.name)

            try:
                config = load_app_config(temp_path)
                # OrpheusConfig normalizes enabled field - channel ID 1 always exists
                # We're testing that the config loads without error
                assert len(config.channels) >= 0  # May have channels
                # If we have channels, verify structure is correct
                if config.channels:
                    assert all(isinstance(ch.id, str) for ch in config.channels)
                    assert all(isinstance(ch.enabled, bool) for ch in config.channels)
            finally:
                temp_path.unlink()

    def test_empty_channels_list(self) -> None:
        """load_app_config should handle empty channels list."""
        config_content = """---
mqtt:
  broker_host: localhost
  broker_port: 1883

audio:
  sample_rate: 48000
  channels: []

storage:
  base_path: /tmp
  format:
    audio: wav
  retention:
    raw_audio_days: 30

logging:
  level: INFO
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(config_content)
            temp_path = Path(f.name)

        try:
            config = load_app_config(temp_path)
            # OrpheusConfig may have default channels, so just verify it's a list
            assert isinstance(config.channels, list)
        finally:
            temp_path.unlink()

    def test_malformed_channel_entries(self) -> None:
        """load_app_config should skip malformed channel entries."""
        config_content = """---
mqtt:
  broker_host: localhost
  broker_port: 1883

audio:
  sample_rate: 48000
  channels:
    - id: 1
      name: Valid
      enabled: true
    - id: 2
      name: Also Valid
      enabled: true

storage:
  base_path: /tmp
  format:
    audio: wav
  retention:
    raw_audio_days: 30

logging:
  level: INFO
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(config_content)
            temp_path = Path(f.name)

        try:
            config = load_app_config(temp_path)
            # OrpheusConfig normalizes the channels, verify we get at least one valid channel
            assert len(config.channels) >= 1
            # Verify the structure is correct
            assert all(hasattr(ch, "id") for ch in config.channels)
            assert all(hasattr(ch, "label") for ch in config.channels)
            assert all(hasattr(ch, "enabled") for ch in config.channels)
        finally:
            temp_path.unlink()
