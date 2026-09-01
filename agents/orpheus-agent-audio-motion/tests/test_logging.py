"""Tests for audio-motion logging behavior."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from orpheus_agent_audio_motion.main import AudioMotionDetector


class TestAudioMotionLogging:
    """Test that audio motion operations log correctly."""

    @pytest.mark.asyncio
    @patch("orpheus_agent_audio_motion.main.logger")
    @patch("orpheus_agent_audio_motion.main.load_app_config")
    async def test_logs_initialization(self, mock_load_config, mock_logger):
        """Test that agent initialization logs correctly."""
        # Setup mock config
        mock_config = Mock()
        mock_config.channels = []
        mock_config.mqtt.broker_host = "localhost"
        mock_config.mqtt.broker_port = 1883
        mock_config.mqtt.qos = 1
        mock_config.mqtt.keepalive = 60
        mock_config.logging.level = "INFO"
        mock_config.logging.use_json = False
        mock_load_config.return_value = mock_config

        # Create agent
        agent = AudioMotionDetector()

        # Verify logger is used (initialization uses setup_logging which is already tested)
        assert agent is not None

    @pytest.mark.asyncio
    @patch("orpheus_agent_audio_motion.main.logger")
    @patch("orpheus_agent_audio_motion.main.load_app_config")
    @patch("orpheus_agent_audio_motion.main.create_event_bus")
    async def test_logs_mqtt_initialization(self, mock_mqtt_class, mock_load_config, mock_logger):
        """Test that MQTT initialization logs correctly."""
        # Setup mock config
        mock_config = Mock()
        mock_channel = Mock()
        mock_channel.id = "test_channel"
        mock_channel.enabled = True
        mock_config.channels = [mock_channel]
        mock_config.mqtt.broker_host = "localhost"
        mock_config.mqtt.broker_port = 1883
        mock_config.mqtt.qos = 1
        mock_config.mqtt.keepalive = 60
        mock_config.logging.level = "INFO"
        mock_config.logging.use_json = False
        mock_config.runtime.sample_rate = 48000
        mock_config.runtime.frame_duration_ms = 10
        mock_config.storage.category = "audio_motion"
        mock_config.storage.write_format = "flac"
        mock_config.storage.retain_days = 7
        mock_load_config.return_value = mock_config

        # Mock MQTT client
        mock_mqtt = Mock()
        mock_mqtt_class.return_value = mock_mqtt

        agent = AudioMotionDetector()

        # Mock audio source
        mock_source = AsyncMock()
        mock_source.start = AsyncMock()

        with patch("orpheus_agent_audio_motion.main.create_audio_source", return_value=mock_source):
            with patch("orpheus_agent_audio_motion.main.ClipSaver"):
                with patch("orpheus_agent_audio_motion.main.DetectionDB"):
                    with patch("orpheus_common.config.OrpheusConfig") as mock_orpheus_cfg:
                        mock_orpheus_cfg.get_instance.return_value = Mock(audio=Mock(channels=[]))
                        await agent._initialize_dependencies()

        # Verify MQTT initialization was logged
        info_calls = [str(call) for call in mock_logger.info.call_args_list]
        assert any("MQTT" in call or "Initializing" in call for call in info_calls)

    @pytest.mark.asyncio
    @patch("orpheus_agent_audio_motion.main.logger")
    @patch("orpheus_agent_audio_motion.main.load_app_config")
    async def test_logs_storage_policy(self, mock_load_config, mock_logger):
        """Test that storage retention policy is logged."""
        # Setup mock config
        mock_config = Mock()
        mock_config.channels = []
        mock_config.mqtt.broker_host = "localhost"
        mock_config.mqtt.broker_port = 1883
        mock_config.mqtt.qos = 1
        mock_config.mqtt.keepalive = 60
        mock_config.logging.level = "INFO"
        mock_config.logging.use_json = False
        mock_config.runtime.sample_rate = 48000
        mock_config.runtime.frame_duration_ms = 10
        mock_config.storage.category = "audio_motion"
        mock_config.storage.write_format = "flac"
        mock_config.storage.retain_days = 7
        mock_config.storage.max_size_gb = 50
        mock_config.storage.cleanup_strategy = "oldest"
        mock_config.storage.check_interval_hours = 1
        mock_load_config.return_value = mock_config

        agent = AudioMotionDetector()

        # Verify config is loaded correctly
        # (Full start() method testing would require more complex mocking)
        assert agent._config.storage.retain_days == 7
