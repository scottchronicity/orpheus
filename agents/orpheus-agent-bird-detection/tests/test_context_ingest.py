"""Tests for spatiotemporal context ingestion and propagation in bird detection agent."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import Mock, patch

import numpy as np
import pytest
from orpheus_common.events import SpatiotemporalContext

from orpheus_agent_bird_detection.main import BirdDetectionAgent


class TestContextIngest:
    """Tests verifying context is ingested from audio events and propagated to bird events."""

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
    @patch("orpheus_agent_bird_detection.main.sf.read")
    def test_context_propagated_from_audio_to_bird_event(
        self,
        mock_sf_read: Mock,
        mock_orpheus_config_class: Mock,
        mock_load_config: Mock,
        mock_config: Mock,
    ) -> None:
        """Context from audio motion event should be propagated to bird detection event."""
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

        # V2 payload with spatiotemporal context (as produced by refactored audio agent)
        v2_payload: dict[str, Any] = {
            "event_id": "test-event-uuid-001",
            "event_timestamp": datetime.now(timezone.utc).isoformat(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "detection_type": "audio.motion",
            "channel": 1,
            "audio_clip_path": "/data/orpheus/audio/test.flac",
            "context": {
                "lat": 40.7128,
                "lon": -74.0060,
                "elevation": 10.5,
                "sensor_id": "mic-1",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            "metadata": {
                "channel_id": "1",
                "duration_seconds": 2.0,
                "peak_energy_db": -20.0,
                "average_energy_db": -25.0,
                "frame_count": 10,
            },
        }

        agent._on_audio_motion_event("orpheus/audio/motion/events", v2_payload)

        # Verify MQTT publish was called
        agent.mqtt_client.publish.assert_called_once()
        published_topic, published_event = agent.mqtt_client.publish.call_args[0]

        assert published_topic == "orpheus/detection/bird/events"

        # The outgoing event should contain the same context as the incoming event
        assert published_event["context"] is not None
        assert published_event["context"]["lat"] == 40.7128
        assert published_event["context"]["lon"] == -74.0060
        assert published_event["context"]["elevation"] == 10.5
        assert published_event["context"]["sensor_id"] == "mic-1"

        # Verify source_event_id is set
        assert published_event["source_event_id"] == "test-event-uuid-001"

        # Verify detection_type
        assert published_event["detection_type"] == "species.detected"

    @patch("orpheus_agent_bird_detection.main.load_config")
    @patch("orpheus_agent_bird_detection.main.OrpheusConfig")
    @patch("orpheus_agent_bird_detection.main.sf.read")
    def test_context_propagated_to_database_storage(
        self,
        mock_sf_read: Mock,
        mock_orpheus_config_class: Mock,
        mock_load_config: Mock,
        mock_config: Mock,
    ) -> None:
        """Context should also be propagated when storing detections in the database."""
        mock_load_config.return_value = mock_config
        mock_orpheus_config_class.get_instance.return_value = Mock(
            mqtt=Mock(broker_host="localhost", broker_port=1883)
        )

        audio_data = np.random.randn(48000)
        mock_sf_read.return_value = (audio_data, 48000)

        agent = BirdDetectionAgent()
        agent.model = Mock()
        agent.mqtt_client = Mock()
        agent.detection_db = Mock()

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

        v2_payload: dict[str, Any] = {
            "event_id": "test-event-uuid-002",
            "event_timestamp": datetime.now(timezone.utc).isoformat(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "detection_type": "audio.motion",
            "channel": 1,
            "audio_clip_path": "/data/orpheus/audio/test.flac",
            "context": {
                "lat": 47.6062,
                "lon": -122.3321,
                "sensor_id": "mic-1",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            "metadata": {},
        }

        agent._on_audio_motion_event("orpheus/audio/motion/events", v2_payload)

        # Verify database save was called
        assert agent.detection_db.save.called
        saved_detection = agent.detection_db.save.call_args[0][0]

        # Verify context is preserved in database entry
        assert saved_detection.context is not None
        assert saved_detection.context.lat == 47.6062
        assert saved_detection.context.lon == -122.3321

    @patch("orpheus_agent_bird_detection.main.load_config")
    @patch("orpheus_agent_bird_detection.main.OrpheusConfig")
    @patch("orpheus_agent_bird_detection.main.sf.read")
    def test_backward_compatible_with_old_payload(
        self,
        mock_sf_read: Mock,
        mock_orpheus_config_class: Mock,
        mock_load_config: Mock,
        mock_config: Mock,
    ) -> None:
        """Old-style payloads without context should still work."""
        mock_load_config.return_value = mock_config
        mock_orpheus_config_class.get_instance.return_value = Mock(
            mqtt=Mock(broker_host="localhost", broker_port=1883)
        )

        audio_data = np.random.randn(48000)
        mock_sf_read.return_value = (audio_data, 48000)

        agent = BirdDetectionAgent()
        agent.model = Mock()
        agent.mqtt_client = Mock()
        agent.detection_db = Mock()

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

        # Old-style V1 payload (no context, no Detection schema)
        old_payload: dict[str, Any] = {
            "event_id": "audio_motion_old_001",
            "channel_id": "1",
            "clip_path": "/data/orpheus/audio/test.flac",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": 2.0,
        }

        agent._on_audio_motion_event("orpheus/audio/motion/events", old_payload)

        # Should still process and publish
        agent.model.predict.assert_called_once()
        agent.mqtt_client.publish.assert_called_once()

        published_topic, published_event = agent.mqtt_client.publish.call_args[0]
        assert published_topic == "orpheus/detection/bird/events"
        assert published_event["detection_type"] == "species.detected"
        # Context should be None since old payload had none
        assert published_event["context"] is None

    @patch("orpheus_agent_bird_detection.main.load_config")
    @patch("orpheus_agent_bird_detection.main.OrpheusConfig")
    def test_create_detection_event_with_context(
        self,
        mock_orpheus_config_class: Mock,
        mock_load_config: Mock,
        mock_config: Mock,
    ) -> None:
        """_create_detection_event should accept and include source context."""
        mock_load_config.return_value = mock_config
        mock_orpheus_config_class.get_instance.return_value = Mock(
            mqtt=Mock(broker_host="localhost", broker_port=1883)
        )

        agent = BirdDetectionAgent()

        context = SpatiotemporalContext(
            lat=40.7128,
            lon=-74.0060,
            sensor_id="mic-1",
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

        event = agent._create_detection_event(
            detections=detections,
            source_event_id="source-uuid-123",
            channel_id="1",
            clip_path="/data/test.flac",
            inference_time_ms=100,
            source_context=context,
        )

        assert event.context is not None
        assert event.context.lat == 40.7128
        assert event.context.lon == -74.0060
        assert event.context.sensor_id == "mic-1"
        assert event.source_event_id == "source-uuid-123"
        assert event.detection_type == "species.detected"
