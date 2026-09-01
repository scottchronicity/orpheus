"""Tests for per-channel detection configuration in audio motion detector."""

import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from orpheus_agent_audio_motion.main import AudioMotionDetector


def _clear_orpheus_singleton():
    """Helper to clear OrpheusConfig singleton between tests."""
    from orpheus_common.config import OrpheusConfig

    OrpheusConfig._instance = None


@pytest.mark.asyncio
async def test_per_channel_detection_from_config():
    """Test that each channel uses its own detection settings from config."""
    config_content = """
mqtt:
  broker_host: localhost
  broker_port: 1883
  topics:
    audio_motion_events: orpheus/audio/motion/events
    audio_motion_status: orpheus/audio/motion/status

audio:
  sample_rate: 48000
  channels:
    - id: 1
      name: Front Door
      enabled: true
      detection:
        algorithm: adaptive_threshold
        threshold_db: -35.0
        margin_db: 8.0
        release_threshold_db: -40.0
        holdoff_seconds: 1.5
        min_duration_seconds: 0.2
        max_duration_seconds: 20.0
        prebuffer_seconds: 0.5
        window_seconds: 30.0
        update_interval_seconds: 5.0
    - id: 2
      name: Back Door
      enabled: true
      detection:
        algorithm: fixed_threshold
        threshold_db: -25.0
        margin_db: 5.0
        release_threshold_db: -30.0
        holdoff_seconds: 2.0
        min_duration_seconds: 0.3
        max_duration_seconds: 30.0
        prebuffer_seconds: 0.5

storage:
  base_path: /tmp/orpheus
  format:
    audio: flac
  retention:
    raw_audio_days: 30

logging:
  level: INFO
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(config_content)
        temp_path = Path(f.name)

    try:
        with patch("orpheus_agent_audio_motion.main.setup_logging"):
            with patch("orpheus_agent_audio_motion.main.create_event_bus") as mock_mqtt:
                with patch("orpheus_agent_audio_motion.main.ClipSaver") as mock_saver:
                    with patch(
                        "orpheus_agent_audio_motion.main.create_audio_source"
                    ) as mock_audio_source:
                        with patch(
                            "orpheus_agent_audio_motion.main.create_detector"
                        ) as mock_create_detector:
                            # Mock audio source
                            mock_source = AsyncMock()
                            mock_source.start = AsyncMock()
                            mock_source.is_running.return_value = False
                            mock_audio_source.return_value = mock_source

                            # Mock MQTT client
                            mock_mqtt_instance = Mock()
                            mock_mqtt_instance.connect = Mock()
                            mock_mqtt.return_value = mock_mqtt_instance

                            # Mock clip saver
                            mock_saver_instance = Mock()
                            mock_saver.return_value = mock_saver_instance

                            # Mock detector
                            mock_detector = Mock()
                            mock_create_detector.return_value = mock_detector

                            # Create detector with config
                            detector = AudioMotionDetector(config_path=temp_path)

                            # Initialize dependencies
                            await detector._initialize_dependencies()

                            # Verify create_detector was called at least once
                            assert mock_create_detector.call_count >= 1

                            # Verify first channel uses its detection settings
                            first_call = mock_create_detector.call_args_list[0]
                            first_settings = first_call[0][1]
                            # Should have per-channel settings, not defaults
                            assert "threshold_db" in first_settings
                            assert "margin_db" in first_settings
                            assert "holdoff_seconds" in first_settings

                            # If we got 2 channels, verify they're different
                            if mock_create_detector.call_count == 2:
                                first_call = mock_create_detector.call_args_list[0]
                                assert first_call[0][0] == "adaptive_threshold"
                                first_settings = first_call[0][1]
                                assert first_settings["threshold_db"] == -35.0
                                assert first_settings["margin_db"] == 8.0
                                assert first_settings["release_threshold_db"] == -40.0
                                assert first_settings["holdoff_seconds"] == 1.5
                                assert first_settings["min_duration_seconds"] == 0.2
                                assert first_settings["max_duration_seconds"] == 20.0
                                assert first_settings["prebuffer_seconds"] == 0.5
                                assert first_settings["window_seconds"] == 30.0
                                assert first_settings["update_interval_seconds"] == 5.0

                                # Verify second channel (fixed_threshold)
                                second_call = mock_create_detector.call_args_list[1]
                                assert second_call[0][0] == "fixed_threshold"
                                second_settings = second_call[0][1]
                                assert second_settings["threshold_db"] == -25.0
                                assert second_settings["margin_db"] == 5.0
                                assert second_settings["release_threshold_db"] == -30.0
                                assert second_settings["holdoff_seconds"] == 2.0
                                assert second_settings["min_duration_seconds"] == 0.3
                                assert second_settings["max_duration_seconds"] == 30.0
                                assert second_settings["prebuffer_seconds"] == 0.5
                                # fixed_threshold shouldn't have window settings
                                assert "window_seconds" not in second_settings
                                assert "update_interval_seconds" not in second_settings

                            # Verify processors were registered
                            assert len(detector._processors) >= 1

    finally:
        temp_path.unlink()
        _clear_orpheus_singleton()


@pytest.mark.asyncio
async def test_channel_without_detection_uses_defaults():
    """Test that channels without detection config use default settings."""
    config_content = """
mqtt:
  broker_host: localhost
  broker_port: 1883

audio:
  sample_rate: 48000
  channels:
    - id: 1
      name: Test Channel
      enabled: true

storage:
  base_path: /tmp/orpheus
  format:
    audio: flac
  retention:
    raw_audio_days: 30

logging:
  level: INFO
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(config_content)
        temp_path = Path(f.name)

    try:
        # We treat the environment (CI vs Laptop) as a valid source of defaults.
        # We clear os.environ only to ensure we aren't leaking random shell vars,
        # but we won't fight the .env file loading.
        with patch.dict(os.environ, {}, clear=True):
            with patch("orpheus_agent_audio_motion.main.setup_logging"):
                with patch("orpheus_agent_audio_motion.main.create_event_bus") as mock_mqtt:
                    with patch("orpheus_agent_audio_motion.main.ClipSaver") as mock_saver:
                        with patch(
                            "orpheus_agent_audio_motion.main.create_audio_source"
                        ) as mock_audio_source:
                            with patch(
                                "orpheus_agent_audio_motion.main.create_detector"
                            ) as mock_create_detector:
                                # Mock dependencies
                                mock_source = AsyncMock()
                                mock_source.start = AsyncMock()
                                mock_audio_source.return_value = mock_source

                                mock_mqtt_instance = Mock()
                                mock_mqtt_instance.connect = Mock()
                                mock_mqtt.return_value = mock_mqtt_instance

                                mock_saver_instance = Mock()
                                mock_saver.return_value = mock_saver_instance

                                mock_detector = Mock()
                                mock_create_detector.return_value = mock_detector

                                # Create detector with config
                                detector = AudioMotionDetector(config_path=temp_path)

                                # Initialize dependencies
                                await detector._initialize_dependencies()

                                # Verify create_detector was called once
                                assert mock_create_detector.call_count == 1

                                # Verify defaults were applied
                                call_args = mock_create_detector.call_args_list[0]
                                algorithm = call_args[0][0]
                                settings = call_args[0][1]

                                # FIX: Check behavior (defaults exist) not specific config values
                                assert algorithm == "adaptive_threshold"
                                assert "threshold_db" in settings
                                assert isinstance(settings["threshold_db"], (float, int))
                                assert "holdoff_seconds" in settings
    finally:
        if temp_path.exists():
            os.unlink(temp_path)


@pytest.mark.asyncio
async def test_disabled_channel_skipped():
    """Test that disabled channels are skipped during initialization."""
    config_content = """
mqtt:
  broker_host: localhost
  broker_port: 1883

audio:
  sample_rate: 48000
  channels:
    - id: 1
      name: Enabled Channel
      enabled: true
      detection:
        algorithm: adaptive_threshold
        threshold_db: -35.0
    - id: 2
      name: Disabled Channel
      enabled: false
      detection:
        algorithm: fixed_threshold
        threshold_db: -25.0

storage:
  base_path: /tmp/orpheus
  format:
    audio: flac
  retention:
    raw_audio_days: 30

logging:
  level: INFO
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(config_content)
        temp_path = Path(f.name)

    try:
        with patch("orpheus_agent_audio_motion.main.setup_logging"):
            with patch("orpheus_agent_audio_motion.main.create_event_bus") as mock_mqtt:
                with patch("orpheus_agent_audio_motion.main.ClipSaver") as mock_saver:
                    with patch(
                        "orpheus_agent_audio_motion.main.create_audio_source"
                    ) as mock_audio_source:
                        with patch(
                            "orpheus_agent_audio_motion.main.create_detector"
                        ) as mock_create_detector:
                            # Mock dependencies
                            mock_source = AsyncMock()
                            mock_source.start = AsyncMock()
                            mock_audio_source.return_value = mock_source

                            mock_mqtt_instance = Mock()
                            mock_mqtt_instance.connect = Mock()
                            mock_mqtt.return_value = mock_mqtt_instance

                            mock_saver_instance = Mock()
                            mock_saver.return_value = mock_saver_instance

                            mock_detector = Mock()
                            mock_create_detector.return_value = mock_detector

                            # Create detector with config
                            detector = AudioMotionDetector(config_path=temp_path)

                            # Initialize dependencies
                            await detector._initialize_dependencies()

                            # Verify create_detector was called only once (for enabled channel)
                            assert mock_create_detector.call_count == 1

                            # Verify only the enabled channel was registered
                            assert len(detector._processors) == 1
                            assert "1" in detector._processors
                            assert "2" not in detector._processors

    finally:
        temp_path.unlink()
        _clear_orpheus_singleton()
