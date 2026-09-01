"""Tests for bird detection logging behavior."""

from unittest.mock import Mock, patch

import numpy as np

from orpheus_agent_bird_detection.main import BirdDetectionAgent


class TestBirdDetectionLogging:
    """Test that bird detection operations log correctly."""

    @patch("orpheus_agent_bird_detection.main.logger")
    @patch("orpheus_agent_bird_detection.main.sf.read")
    @patch("orpheus_agent_bird_detection.main.load_config")
    @patch("orpheus_agent_bird_detection.main.OrpheusConfig")
    def test_logs_audio_loading(
        self, mock_orpheus_config_class, mock_load_config, mock_sf_read, mock_logger
    ):
        """Test that audio loading is logged."""
        # Setup mocks
        mock_config = Mock()
        mock_config.model_path = "/fake/model.onnx"
        mock_config.confidence_threshold = 0.5
        mock_load_config.return_value = mock_config

        mock_orpheus = Mock()
        mock_orpheus.mqtt.broker_host = "localhost"
        mock_orpheus.mqtt.broker_port = 1883
        mock_orpheus_config_class.get_instance.return_value = mock_orpheus

        agent = BirdDetectionAgent()

        # Mock BirdNET model
        mock_model = Mock()
        mock_model.predict.return_value = []
        agent.model = mock_model

        # Mock audio read
        mock_audio = np.random.randn(48000).astype(np.float32)
        mock_sf_read.return_value = (mock_audio, 48000)

        # Call the method
        payload = {
            "clip_path": "/test/audio.flac",
            "channel_id": "1",
            "event_id": "test_001",
        }
        agent._on_audio_motion_event("test/topic", payload)

        # Verify logging occurred
        info_calls = [str(call) for call in mock_logger.info.call_args_list]
        assert any("Received audio motion event" in call for call in info_calls)

    @patch("orpheus_agent_bird_detection.main.logger")
    @patch("orpheus_agent_bird_detection.main.sf.read")
    @patch("orpheus_agent_bird_detection.main.load_config")
    @patch("orpheus_agent_bird_detection.main.OrpheusConfig")
    def test_logs_detection_results(
        self, mock_orpheus_config_class, mock_load_config, mock_sf_read, mock_logger
    ):
        """Test that detection results are logged."""
        # Setup mocks
        mock_config = Mock()
        mock_config.model_path = "/fake/model.onnx"
        mock_config.confidence_threshold = 0.5
        mock_load_config.return_value = mock_config

        mock_orpheus = Mock()
        mock_orpheus.mqtt.broker_host = "localhost"
        mock_orpheus.mqtt.broker_port = 1883
        mock_orpheus_config_class.get_instance.return_value = mock_orpheus

        agent = BirdDetectionAgent()

        # Mock BirdNET model with detection
        mock_model = Mock()
        mock_model.predict.return_value = [
            {
                "species_code": "amecro",
                "species_common": "American Crow",
                "confidence": 0.89,
                "start_time": 0.0,
                "end_time": 3.0,
            }
        ]
        agent.model = mock_model

        # Mock MQTT client
        agent.bus = Mock()

        # Mock DetectionDB
        agent.detection_db = Mock()

        # Mock audio read
        mock_audio = np.random.randn(48000).astype(np.float32)
        mock_sf_read.return_value = (mock_audio, 48000)

        # Call the method
        payload = {
            "clip_path": "/test/audio.flac",
            "channel_id": "1",
            "event_id": "test_001",
        }
        agent._on_audio_motion_event("test/topic", payload)

        # Verify detection was logged
        info_calls = [str(call) for call in mock_logger.info.call_args_list]
        assert any("Detected species" in call for call in info_calls)

    @patch("orpheus_agent_bird_detection.main.logger")
    @patch("orpheus_agent_bird_detection.main.load_config")
    @patch("orpheus_agent_bird_detection.main.OrpheusConfig")
    def test_logs_missing_clip_path(self, mock_orpheus_config_class, mock_load_config, mock_logger):
        """Test that missing clip_path is logged."""
        # Setup mocks
        mock_config = Mock()
        mock_load_config.return_value = mock_config

        mock_orpheus = Mock()
        mock_orpheus.mqtt.broker_host = "localhost"
        mock_orpheus.mqtt.broker_port = 1883
        mock_orpheus_config_class.get_instance.return_value = mock_orpheus

        agent = BirdDetectionAgent()

        # Call with missing clip_path
        payload = {"event_id": "test_001", "channel_id": "1"}
        agent._on_audio_motion_event("test/topic", payload)

        # Verify warning was logged
        mock_logger.warning.assert_called()

    @patch("orpheus_agent_bird_detection.main.logger")
    @patch("orpheus_agent_bird_detection.main.sf.read")
    @patch("orpheus_agent_bird_detection.main.load_config")
    @patch("orpheus_agent_bird_detection.main.OrpheusConfig")
    def test_logs_audio_load_failure(
        self, mock_orpheus_config_class, mock_load_config, mock_sf_read, mock_logger
    ):
        """Test that audio load failure is logged."""
        # Setup mocks
        mock_config = Mock()
        mock_config.model_path = "/fake/model.onnx"
        mock_config.confidence_threshold = 0.5
        mock_load_config.return_value = mock_config

        mock_orpheus = Mock()
        mock_orpheus.mqtt.broker_host = "localhost"
        mock_orpheus.mqtt.broker_port = 1883
        mock_orpheus_config_class.get_instance.return_value = mock_orpheus

        agent = BirdDetectionAgent()
        agent.model = Mock()

        # Make audio read fail
        mock_sf_read.side_effect = Exception("File not found")

        # Call the method
        payload = {
            "clip_path": "/test/audio.flac",
            "channel_id": "1",
            "event_id": "test_001",
        }
        agent._on_audio_motion_event("test/topic", payload)

        # Verify error was logged
        mock_logger.error.assert_called()
