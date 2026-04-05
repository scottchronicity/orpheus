"""Tests for main bird detection agent."""

from datetime import datetime, timezone
from unittest.mock import Mock, patch

import numpy as np
import pytest
from orpheus_common.detection import Detection

from orpheus_agent_bird_detection.main import BirdDetectionAgent


class TestBirdDetectionAgent:
    """Tests for BirdDetectionAgent."""

    @pytest.fixture
    def mock_config(self) -> Mock:
        """Create mock configuration."""
        config = Mock()
        config.model_path = "/fake/model.onnx"
        config.confidence_threshold = 0.5
        config.location_lat = 42.5
        config.location_lon = -83.5
        return config

    @pytest.fixture
    def mock_orpheus_config(self) -> Mock:
        """Create mock Orpheus configuration."""
        config = Mock()
        config.mqtt.broker_host = "localhost"
        config.mqtt.broker_port = 1883
        return config

    @patch("orpheus_agent_bird_detection.main.load_config")
    @patch("orpheus_agent_bird_detection.main.OrpheusConfig")
    def test_agent_init(
        self, mock_orpheus_config_class: Mock, mock_load_config: Mock, mock_config: Mock
    ) -> None:
        """Should initialize agent."""
        mock_load_config.return_value = mock_config
        mock_orpheus_config_class.get_instance.return_value = Mock(
            mqtt=Mock(broker_host="localhost", broker_port=1883)
        )

        agent = BirdDetectionAgent()

        assert agent.config == mock_config
        assert agent.events_processed == 0
        assert agent.detections_found == 0

    @patch("orpheus_agent_bird_detection.main.load_config")
    @patch("orpheus_agent_bird_detection.main.OrpheusConfig")
    def test_create_detection_event(
        self, mock_orpheus_config_class: Mock, mock_load_config: Mock, mock_config: Mock
    ) -> None:
        """Should create properly formatted detection event."""
        mock_load_config.return_value = mock_config
        mock_orpheus_config_class.get_instance.return_value = Mock(
            mqtt=Mock(broker_host="localhost", broker_port=1883)
        )

        agent = BirdDetectionAgent()
        agent.events_processed = 5

        detections = [
            {
                "species_code": "amecro",
                "species_common": "American Crow",
                "species_scientific": "Corvus brachyrhynchos",
                "confidence": 0.87,
                "start_time": 0.5,
                "end_time": 1.2,
            }
        ]

        event = agent._create_detection_event(
            detections=detections,
            source_event_id="audio_motion_123",
            channel_id="1",
            clip_path="/data/orpheus/audio/test.flac",
            inference_time_ms=145,
        )

        assert event.event_id is not None
        assert event.source_event_id == "audio_motion_123"
        assert event.channel == 1
        assert event.detection_type == "species.detected"
        assert event.audio_clip_path == "/data/orpheus/audio/test.flac"
        assert len(event.metadata["detections"]) == 1
        assert event.metadata["detections"][0]["species_code"] == "amecro"
        assert event.metadata["model_version"] == "BirdNET_V2.4"
        assert event.metadata["inference_time_ms"] == 145

    @patch("orpheus_agent_bird_detection.main.load_config")
    @patch("orpheus_agent_bird_detection.main.OrpheusConfig")
    @patch("orpheus_agent_bird_detection.main.sf.read")
    def test_load_audio(
        self,
        mock_sf_read: Mock,
        mock_orpheus_config_class: Mock,
        mock_load_config: Mock,
        mock_config: Mock,
    ) -> None:
        """Should load audio file correctly."""
        mock_load_config.return_value = mock_config
        mock_orpheus_config_class.get_instance.return_value = Mock(
            mqtt=Mock(broker_host="localhost", broker_port=1883)
        )

        # Mock audio file reading
        audio_data = np.random.randn(48000)  # 1 second at 48kHz
        mock_sf_read.return_value = (audio_data, 48000)

        agent = BirdDetectionAgent()
        audio, sample_rate = agent._load_audio("/fake/audio.flac")

        assert audio is not None
        assert sample_rate == 48000
        assert len(audio) == 48000

    @patch("orpheus_agent_bird_detection.main.load_config")
    @patch("orpheus_agent_bird_detection.main.OrpheusConfig")
    @patch("orpheus_agent_bird_detection.main.sf.read")
    def test_load_audio_stereo_to_mono(
        self,
        mock_sf_read: Mock,
        mock_orpheus_config_class: Mock,
        mock_load_config: Mock,
        mock_config: Mock,
    ) -> None:
        """Should convert stereo audio to mono."""
        mock_load_config.return_value = mock_config
        mock_orpheus_config_class.get_instance.return_value = Mock(
            mqtt=Mock(broker_host="localhost", broker_port=1883)
        )

        # Mock stereo audio
        stereo_audio = np.random.randn(48000, 2)
        mock_sf_read.return_value = (stereo_audio, 48000)

        agent = BirdDetectionAgent()
        audio, _sample_rate = agent._load_audio("/fake/audio.flac")

        assert audio is not None
        assert len(audio.shape) == 1  # Should be mono
        assert len(audio) == 48000

    @patch("orpheus_agent_bird_detection.main.load_config")
    @patch("orpheus_agent_bird_detection.main.OrpheusConfig")
    @patch("orpheus_agent_bird_detection.main.sf.read")
    def test_load_audio_error_handling(
        self,
        mock_sf_read: Mock,
        mock_orpheus_config_class: Mock,
        mock_load_config: Mock,
        mock_config: Mock,
    ) -> None:
        """Should handle audio loading errors gracefully."""
        mock_load_config.return_value = mock_config
        mock_orpheus_config_class.get_instance.return_value = Mock(
            mqtt=Mock(broker_host="localhost", broker_port=1883)
        )

        mock_sf_read.side_effect = Exception("File not found")

        agent = BirdDetectionAgent()
        audio, sample_rate = agent._load_audio("/fake/audio.flac")

        assert audio is None
        assert sample_rate == 0

    @patch("orpheus_agent_bird_detection.main.load_config")
    @patch("orpheus_agent_bird_detection.main.OrpheusConfig")
    def test_on_audio_motion_event_missing_clip_path(
        self, mock_orpheus_config_class: Mock, mock_load_config: Mock, mock_config: Mock
    ) -> None:
        """Should handle events missing clip_path."""
        mock_load_config.return_value = mock_config
        mock_orpheus_config_class.get_instance.return_value = Mock(
            mqtt=Mock(broker_host="localhost", broker_port=1883)
        )

        agent = BirdDetectionAgent()
        agent.model = Mock()

        # Event without clip_path
        agent._on_audio_motion_event("orpheus/audio/motion/events", {"event_id": "test"})

        # Should not process
        agent.model.predict.assert_not_called()

    @patch("orpheus_agent_bird_detection.main.load_config")
    @patch("orpheus_agent_bird_detection.main.OrpheusConfig")
    @patch("orpheus_agent_bird_detection.main.sf.read")
    def test_on_audio_motion_event_with_detections(
        self,
        mock_sf_read: Mock,
        mock_orpheus_config_class: Mock,
        mock_load_config: Mock,
        mock_config: Mock,
    ) -> None:
        """Should process event and publish detections."""
        mock_load_config.return_value = mock_config
        mock_orpheus_config_class.get_instance.return_value = Mock(
            mqtt=Mock(broker_host="localhost", broker_port=1883)
        )

        # Mock audio loading
        audio_data = np.random.randn(48000)
        mock_sf_read.return_value = (audio_data, 48000)

        agent = BirdDetectionAgent()
        agent.model = Mock()
        agent.mqtt_client = Mock()
        agent.detection_db = Mock()

        # Mock detections
        detections = [
            {
                "species_code": "amecro",
                "species_common": "American Crow",
                "species_scientific": "Corvus brachyrhynchos",
                "confidence": 0.87,
                "start_time": 0.5,
                "end_time": 1.2,
            }
        ]
        agent.model.predict.return_value = detections

        event = {
            "event_id": "audio_motion_001",
            "channel_id": "1",
            "clip_path": "/data/orpheus/audio/test.flac",
        }

        agent._on_audio_motion_event("orpheus/audio/motion/events", event)

        # Should call model
        agent.model.predict.assert_called_once()

        # Should publish to MQTT
        agent.mqtt_client.publish.assert_called_once()
        published_topic, published_event = agent.mqtt_client.publish.call_args[0]
        assert published_topic == "orpheus/detection/bird/events"
        assert len(published_event["metadata"]["detections"]) == 1

        # Should store in DB
        assert agent.detection_db.save.called

    @patch("orpheus_agent_bird_detection.main.load_config")
    @patch("orpheus_agent_bird_detection.main.OrpheusConfig")
    @patch("orpheus_agent_bird_detection.main.sf.read")
    def test_on_audio_motion_event_no_detections(
        self,
        mock_sf_read: Mock,
        mock_orpheus_config_class: Mock,
        mock_load_config: Mock,
        mock_config: Mock,
    ) -> None:
        """Should handle case with no detections."""
        mock_load_config.return_value = mock_config
        mock_orpheus_config_class.get_instance.return_value = Mock(
            mqtt=Mock(broker_host="localhost", broker_port=1883)
        )

        # Mock audio loading
        audio_data = np.random.randn(48000)
        mock_sf_read.return_value = (audio_data, 48000)

        agent = BirdDetectionAgent()
        agent.model = Mock()
        agent.mqtt_client = Mock()
        agent.detection_db = Mock()

        # No detections
        agent.model.predict.return_value = []

        event = {
            "event_id": "audio_motion_001",
            "channel_id": "1",
            "clip_path": "/data/orpheus/audio/test.flac",
        }

        agent._on_audio_motion_event("orpheus/audio/motion/events", event)

        # Should call model
        agent.model.predict.assert_called_once()

        # Should NOT publish to MQTT or save to DB
        agent.mqtt_client.publish.assert_not_called()
        agent.detection_db.save.assert_not_called()

    @patch("orpheus_agent_bird_detection.main.load_config")
    @patch("orpheus_agent_bird_detection.main.OrpheusConfig")
    def test_store_detections(
        self, mock_orpheus_config_class: Mock, mock_load_config: Mock, mock_config: Mock
    ) -> None:
        """Should store detections in database."""
        mock_load_config.return_value = mock_config
        mock_orpheus_config_class.get_instance.return_value = Mock(
            mqtt=Mock(broker_host="localhost", broker_port=1883)
        )

        agent = BirdDetectionAgent()
        agent.detection_db = Mock()

        event = Detection(
            event_id="bird_det_001",
            timestamp=datetime(2025, 12, 5, 12, 0, 0, tzinfo=timezone.utc),
            detection_type="species.detected",
            channel=1,
            audio_clip_path="/data/test.flac",
            source_event_id="audio_motion_001",
            metadata={
                "model_version": "BirdNET_V2.4",
                "inference_time_ms": 145,
            },
        )

        detections = [
            {
                "species_code": "amecro",
                "species_common": "American Crow",
                "confidence": 0.87,
                "start_time": 0.5,
                "end_time": 1.2,
            }
        ]

        agent._store_detections(event, detections)

        # Should save to database
        assert agent.detection_db.save.called
        saved_detection = agent.detection_db.save.call_args[0][0]
        assert saved_detection.species_code == "amecro"
        assert saved_detection.confidence == 0.87
