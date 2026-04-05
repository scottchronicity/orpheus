"""Tests for crow detection agent main module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from orpheus_agent_crow_detection.classifier import CrowDetectionResult
from orpheus_agent_crow_detection.main import CrowDetectionAgent, main


class TestCrowDetectionAgent:
    """Tests for CrowDetectionAgent class."""

    @patch("orpheus_agent_crow_detection.main.load_config")
    @patch("orpheus_agent_crow_detection.main.OrpheusConfig.get_instance")
    def test_init(self, mock_get_instance: MagicMock, mock_load_config: MagicMock) -> None:
        """Test agent initialization."""
        mock_orpheus_config = MagicMock()
        mock_get_instance.return_value = mock_orpheus_config
        mock_config = MagicMock()
        mock_load_config.return_value = mock_config

        agent = CrowDetectionAgent()

        assert agent.config == mock_config
        assert agent.orpheus_config == mock_orpheus_config
        assert agent.mqtt_client is None
        assert agent.embedder is None
        assert agent.classifier is None
        assert agent.detection_db is None
        assert agent.events_processed == 0
        assert agent.detections_found == 0

    @patch("orpheus_agent_crow_detection.main.load_config")
    @patch("orpheus_agent_crow_detection.main.OrpheusConfig.get_instance")
    def test_init_with_config_path(
        self, mock_get_instance: MagicMock, mock_load_config: MagicMock
    ) -> None:
        """Test agent initialization with custom config path."""
        config_path = Path("/custom/config.yaml")
        CrowDetectionAgent(config_path=config_path)

        mock_load_config.assert_called_once_with(config_path)
        mock_get_instance.assert_called_once_with(config_path=config_path)

    @patch("orpheus_agent_crow_detection.main.sf.read")
    @patch("orpheus_agent_crow_detection.main.CrowDetectionAgent._generate_event_id")
    @patch("orpheus_agent_crow_detection.main.OrpheusConfig.get_instance")
    @patch("orpheus_agent_crow_detection.main.load_config")
    def test_process_audio_file_positive_detection(
        self,
        mock_load_config: MagicMock,
        mock_get_instance: MagicMock,
        mock_generate_id: MagicMock,
        mock_sf_read: MagicMock,
    ) -> None:
        """Test processing audio file with positive crow detection."""
        # Setup mocked config
        mock_config = MagicMock()
        mock_config.embedder_sample_rate = 16000
        mock_config.quality_threshold = 0.5
        mock_load_config.return_value = mock_config

        mock_orpheus_config = MagicMock()
        mock_get_instance.return_value = mock_orpheus_config

        # Setup agent with mocked components
        agent = CrowDetectionAgent()

        # Mock embedder
        mock_embedder = MagicMock()
        mock_embedding = np.random.randn(1, 768).astype(np.float32)
        mock_embedder.generate_embedding.return_value = mock_embedding
        agent.embedder = mock_embedder

        # Mock classifier
        mock_classifier = MagicMock()
        mock_result = CrowDetectionResult(
            is_crow=True,
            quality_score=0.85,
            species="american_crow",
            call_type="caw",
            attributes={"alert": 0.9, "age": "adult"},
        )
        mock_classifier.classify.return_value = mock_result
        agent.classifier = mock_classifier

        # Mock MQTT client
        mock_mqtt = MagicMock()
        agent.mqtt_client = mock_mqtt

        # Mock DetectionDB
        mock_db = MagicMock()
        agent.detection_db = mock_db

        # Mock audio file
        mock_audio = np.random.randn(48000).astype(np.float32)
        mock_sf_read.return_value = (mock_audio, 48000)

        # Mock event ID generation
        mock_generate_id.return_value = "crow_det_test_001"

        # Process audio file
        audio_path = Path("/path/to/audio.flac")
        source_event = {
            "event_id": "audio_motion_001",
            "channel_id": "1",
        }

        agent._process_audio_file(audio_path, source_event)

        # Verify embedder was called
        mock_embedder.generate_embedding.assert_called_once()

        # Verify classifier was called
        mock_classifier.classify.assert_called_once()

        # Verify MQTT publish was called
        assert mock_mqtt.publish.call_count == 1
        publish_args = mock_mqtt.publish.call_args[0]
        assert publish_args[0] == "orpheus/detection/crow/events"
        event = publish_args[1]
        assert event["event_id"] == "crow_det_test_001"
        assert event["species_code"] == "american_crow"
        assert event["metadata"]["call_type"] == "caw"
        assert event["metadata"]["confirmed_crow"] is True

        # Verify detection was added to DB
        mock_db.save.assert_called_once()

        # Verify counter was incremented
        assert agent.detections_found == 1

    @patch("orpheus_agent_crow_detection.main.sf.read")
    @patch("orpheus_agent_crow_detection.main.OrpheusConfig.get_instance")
    @patch("orpheus_agent_crow_detection.main.load_config")
    def test_process_audio_file_negative_detection(
        self, mock_load_config: MagicMock, mock_get_instance: MagicMock, mock_sf_read: MagicMock
    ) -> None:
        """Test processing audio file with no crow detection."""
        # Setup mocked config
        mock_config = MagicMock()
        mock_config.embedder_sample_rate = 16000
        mock_config.quality_threshold = 0.5
        mock_load_config.return_value = mock_config

        mock_orpheus_config = MagicMock()
        mock_get_instance.return_value = mock_orpheus_config

        # Setup agent with mocked components
        agent = CrowDetectionAgent()

        mock_embedder = MagicMock()
        mock_embedding = np.random.randn(1, 768).astype(np.float32)
        mock_embedder.generate_embedding.return_value = mock_embedding
        agent.embedder = mock_embedder

        mock_classifier = MagicMock()
        mock_result = CrowDetectionResult(
            is_crow=False,
            quality_score=0.3,
            species="other",
            call_type=None,
            attributes={},
        )
        mock_classifier.classify.return_value = mock_result
        agent.classifier = mock_classifier

        mock_mqtt = MagicMock()
        agent.mqtt_client = mock_mqtt

        mock_db = MagicMock()
        agent.detection_db = mock_db

        mock_audio = np.random.randn(48000).astype(np.float32)
        mock_sf_read.return_value = (mock_audio, 48000)

        audio_path = Path("/path/to/audio.flac")
        source_event = {"event_id": "audio_motion_001", "channel_id": "1"}

        agent._process_audio_file(audio_path, source_event)

        # Verify MQTT publish was called for negative detection
        mock_mqtt.publish.assert_called_once()
        publish_args = mock_mqtt.publish.call_args[0]
        assert publish_args[0] == "orpheus/detection/crow/events"
        event = publish_args[1]
        assert event["metadata"]["confirmed_crow"] is False

        # Verify detection was saved, but confirmed_crow is False
        mock_db.save.assert_called_once()
        saved_detection = mock_db.save.call_args[0][0]
        assert saved_detection.metadata["confirmed_crow"] is False

        # Verify counter was not incremented
        assert agent.detections_found == 0

    @patch("orpheus_agent_crow_detection.main.OrpheusConfig.get_instance")
    @patch("orpheus_agent_crow_detection.main.load_config")
    def test_on_audio_motion_event_missing_path(
        self, mock_load_config: MagicMock, mock_get_instance: MagicMock
    ) -> None:
        """Test handling bird detection event without audio_clip_path."""
        mock_config = MagicMock()
        mock_load_config.return_value = mock_config
        mock_orpheus_config = MagicMock()
        mock_get_instance.return_value = mock_orpheus_config

        agent = CrowDetectionAgent()

        # Event missing audio_clip_path
        payload = {"event_id": "test", "detections": []}

        # Should not raise exception
        agent._on_bird_detection_event("test/topic", payload)

        assert agent.events_processed == 1

    @patch("orpheus_agent_crow_detection.main.Path.exists")
    @patch("orpheus_agent_crow_detection.main.OrpheusConfig.get_instance")
    @patch("orpheus_agent_crow_detection.main.load_config")
    def test_on_audio_motion_event_missing_file(
        self, mock_load_config: MagicMock, mock_get_instance: MagicMock, mock_exists: MagicMock
    ) -> None:
        """Test handling bird detection event with missing audio file."""
        mock_config = MagicMock()
        mock_load_config.return_value = mock_config
        mock_orpheus_config = MagicMock()
        mock_get_instance.return_value = mock_orpheus_config

        agent = CrowDetectionAgent()
        mock_exists.return_value = False

        payload = {
            "event_id": "test-event-001",
            "event_timestamp": "2024-01-01T00:00:00+00:00",
            "timestamp": "2024-01-01T00:00:00+00:00",
            "detection_type": "species.detected",
            "audio_clip_path": "/missing/file.flac",
            "metadata": {
                "detections": [{"species_code": "amecro", "is_corvid": True}],
            },
        }

        agent._on_bird_detection_event("test/topic", payload)

        assert agent.events_processed == 1

    @patch("orpheus_agent_crow_detection.main.OrpheusConfig.get_instance")
    @patch("orpheus_agent_crow_detection.main.load_config")
    def test_generate_event_id(
        self, mock_load_config: MagicMock, mock_get_instance: MagicMock
    ) -> None:
        """Test event ID generation."""
        mock_config = MagicMock()
        mock_load_config.return_value = mock_config
        mock_orpheus_config = MagicMock()
        mock_get_instance.return_value = mock_orpheus_config

        agent = CrowDetectionAgent()
        agent.detections_found = 5

        event_id = agent._generate_event_id("1")

        assert event_id.startswith("crow_det_")
        assert "_ch1_" in event_id
        assert event_id.endswith("_005")

    @pytest.mark.asyncio
    @patch("orpheus_agent_crow_detection.main.OrpheusConfig.get_instance")
    @patch("orpheus_agent_crow_detection.main.load_config")
    @patch("orpheus_agent_crow_detection.main.setup_logging")
    async def test_start_disabled(
        self,
        mock_setup_logging: MagicMock,
        mock_load_config: MagicMock,
        _mock_get_instance: MagicMock,
    ) -> None:
        """Test agent start when disabled in config."""
        mock_config = MagicMock()
        mock_config.enabled = False
        mock_load_config.return_value = mock_config

        agent = CrowDetectionAgent()

        # Start should return early without loading models
        await agent.start()

        mock_setup_logging.assert_called_once()

    @patch("orpheus_agent_crow_detection.main.OrpheusConfig.get_instance")
    @patch("orpheus_agent_crow_detection.main.load_config")
    @patch("orpheus_agent_crow_detection.main.asyncio.run")
    def test_main_entry_point(
        self,
        mock_asyncio_run: MagicMock,
        mock_load_config: MagicMock,
        mock_get_instance: MagicMock,
    ) -> None:
        """Test main entry point function."""
        mock_config = MagicMock()
        mock_load_config.return_value = mock_config
        mock_orpheus_config = MagicMock()
        mock_get_instance.return_value = mock_orpheus_config

        main()

        # Verify asyncio.run was called with agent.start()
        mock_asyncio_run.assert_called_once()

    @patch("orpheus_agent_crow_detection.main.sf.read")
    @patch("orpheus_agent_crow_detection.main.librosa.resample")
    @patch("orpheus_agent_crow_detection.main.OrpheusConfig.get_instance")
    @patch("orpheus_agent_crow_detection.main.load_config")
    def test_process_audio_file_with_resampling(
        self,
        mock_load_config: MagicMock,
        mock_get_instance: MagicMock,
        mock_resample: MagicMock,
        mock_sf_read: MagicMock,
    ) -> None:
        """Test processing audio file that requires resampling."""
        # Setup mocked config
        mock_config = MagicMock()
        mock_config.embedder_sample_rate = 16000
        mock_config.quality_threshold = 0.5
        mock_load_config.return_value = mock_config

        mock_orpheus_config = MagicMock()
        mock_get_instance.return_value = mock_orpheus_config

        # Setup agent
        agent = CrowDetectionAgent()

        # Mock embedder
        mock_embedder = MagicMock()
        mock_embedding = np.random.randn(1, 768).astype(np.float32)
        mock_embedder.generate_embedding.return_value = mock_embedding
        agent.embedder = mock_embedder

        # Mock classifier
        mock_classifier = MagicMock()
        mock_result = CrowDetectionResult(
            is_crow=False,
            quality_score=0.3,
            species="other",
            call_type=None,
            attributes={},
        )
        mock_classifier.classify.return_value = mock_result
        agent.classifier = mock_classifier

        # Mock MQTT and DB
        agent.mqtt_client = MagicMock()
        agent.detection_db = MagicMock()

        # Mock audio file with 48kHz sample rate (needs resampling)
        mock_audio = np.random.randn(48000).astype(np.float32)
        mock_sf_read.return_value = (mock_audio, 48000)

        # Mock resampled audio
        mock_resampled = np.random.randn(16000).astype(np.float32)
        mock_resample.return_value = mock_resampled

        # Process audio file
        audio_path = Path("/path/to/audio.flac")
        source_event = {"event_id": "audio_motion_001", "channel_id": "1"}

        agent._process_audio_file(audio_path, source_event)

        # Verify librosa.resample was called
        mock_resample.assert_called_once()
        assert mock_resample.call_args[1]["orig_sr"] == 48000
        assert mock_resample.call_args[1]["target_sr"] == 16000

    @patch("orpheus_agent_crow_detection.main.sf.read")
    @patch("orpheus_agent_crow_detection.main.OrpheusConfig.get_instance")
    @patch("orpheus_agent_crow_detection.main.load_config")
    def test_process_audio_file_stereo_to_mono(
        self,
        mock_load_config: MagicMock,
        mock_get_instance: MagicMock,
        mock_sf_read: MagicMock,
    ) -> None:
        """Test processing stereo audio file (converts to mono)."""
        # Setup mocked config
        mock_config = MagicMock()
        mock_config.embedder_sample_rate = 16000
        mock_config.quality_threshold = 0.5
        mock_load_config.return_value = mock_config

        mock_orpheus_config = MagicMock()
        mock_get_instance.return_value = mock_orpheus_config

        # Setup agent
        agent = CrowDetectionAgent()

        # Mock embedder
        mock_embedder = MagicMock()
        mock_embedding = np.random.randn(1, 768).astype(np.float32)
        mock_embedder.generate_embedding.return_value = mock_embedding
        agent.embedder = mock_embedder

        # Mock classifier
        mock_classifier = MagicMock()
        mock_result = CrowDetectionResult(
            is_crow=False,
            quality_score=0.3,
            species="other",
            call_type=None,
            attributes={},
        )
        mock_classifier.classify.return_value = mock_result
        agent.classifier = mock_classifier

        # Mock MQTT and DB
        agent.mqtt_client = MagicMock()
        agent.detection_db = MagicMock()

        # Mock stereo audio file (2 channels)
        mock_audio_stereo = np.random.randn(16000, 2).astype(np.float32)
        mock_sf_read.return_value = (mock_audio_stereo, 16000)

        # Process audio file
        audio_path = Path("/path/to/audio.flac")
        source_event = {"event_id": "audio_motion_001", "channel_id": "1"}

        agent._process_audio_file(audio_path, source_event)

        # Verify embedder was called (with mono audio)
        mock_embedder.generate_embedding.assert_called_once()
