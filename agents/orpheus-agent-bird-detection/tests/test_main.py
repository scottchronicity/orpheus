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
        agent.bus = Mock()
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
        agent.bus.publish.assert_called_once()
        published_topic, published_event = agent.bus.publish.call_args[0]
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
        agent.bus = Mock()
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
        agent.bus.publish.assert_not_called()
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
        # ADR 0011: even with legacy single-window data (no ``windows`` key),
        # _store_detections must still populate an interval from start_time/end_time.
        assert saved_detection.intervals is not None
        assert len(saved_detection.intervals) == 1
        assert saved_detection.intervals[0].start_seconds == 0.5
        assert saved_detection.intervals[0].end_seconds == 1.2

    @patch("orpheus_agent_bird_detection.main.load_config")
    @patch("orpheus_agent_bird_detection.main.OrpheusConfig")
    def test_store_detections_save_failure_bumps_error_feed(
        self, mock_orpheus_config_class: Mock, mock_load_config: Mock, mock_config: Mock
    ) -> None:
        """A DB save failure must reach the cross-agent error feed, not be swallowed."""
        mock_load_config.return_value = mock_config
        mock_orpheus_config_class.get_instance.return_value = Mock(
            mqtt=Mock(broker_host="localhost", broker_port=1883)
        )

        agent = BirdDetectionAgent()
        agent.detection_db = Mock()
        agent.detection_db.save.side_effect = RuntimeError("disk full")

        event = Detection(
            event_id="bird_det_err",
            timestamp=datetime(2025, 12, 5, 12, 0, 0, tzinfo=timezone.utc),
            detection_type="species.detected",
            channel=1,
            audio_clip_path="/data/test.flac",
            source_event_id="audio_motion_err",
            metadata={},
        )
        detections = [
            {
                "species_code": "amecro",
                "species_common": "American Crow",
                "confidence": 0.9,
                "start_time": 0.0,
                "end_time": 1.0,
            }
        ]

        agent._store_detections(event, detections)  # must not raise

        assert agent.errors_count == 1
        assert agent.last_error is not None
        assert agent.last_error.startswith("RuntimeError:")

    @patch("orpheus_agent_bird_detection.main.load_config")
    @patch("orpheus_agent_bird_detection.main.OrpheusConfig")
    def test_store_detections_populates_intervals_from_windows(
        self, mock_orpheus_config_class: Mock, mock_load_config: Mock, mock_config: Mock
    ) -> None:
        """ADR 0011: each window from _merge_detections becomes one interval
        on the persisted Detection."""
        mock_load_config.return_value = mock_config
        mock_orpheus_config_class.get_instance.return_value = Mock(
            mqtt=Mock(broker_host="localhost", broker_port=1883)
        )

        agent = BirdDetectionAgent()
        agent.detection_db = Mock()

        event = Detection(
            event_id="bird_det_002",
            timestamp=datetime(2025, 12, 5, 12, 0, 0, tzinfo=timezone.utc),
            detection_type="species.detected",
            channel=1,
            audio_clip_path="/data/test.flac",
            source_event_id="audio_motion_002",
            metadata={"model_version": "BirdNET_V2.4", "inference_time_ms": 200},
        )

        # Simulated post-_merge_detections output: one species, three windows.
        detections = [
            {
                "species_code": "amecro",
                "species_common": "American Crow",
                "confidence": 0.9,
                "start_time": 3.0,
                "end_time": 6.0,
                "windows": [
                    {"start_time": 0.0, "end_time": 3.0, "confidence": 0.7},
                    {"start_time": 3.0, "end_time": 6.0, "confidence": 0.9},
                    {"start_time": 6.0, "end_time": 9.0, "confidence": 0.6},
                ],
            }
        ]

        agent._store_detections(event, detections)
        saved_detection = agent.detection_db.save.call_args[0][0]
        assert saved_detection.intervals is not None
        assert len(saved_detection.intervals) == 3
        assert [iv.start_seconds for iv in saved_detection.intervals] == [0.0, 3.0, 6.0]
        assert [iv.confidence for iv in saved_detection.intervals] == [0.7, 0.9, 0.6]

    @patch("orpheus_agent_bird_detection.main.load_config")
    @patch("orpheus_agent_bird_detection.main.OrpheusConfig")
    def test_store_detections_populates_ioc_taxonomy_when_scientific_present(
        self, mock_orpheus_config_class: Mock, mock_load_config: Mock, mock_config: Mock
    ) -> None:
        """Layer 1 of cross-classifier identity: when BirdNET's prediction
        carries a species_scientific, the persisted Detection gets a
        TaxonomyRef in the ``ioc`` namespace."""
        mock_load_config.return_value = mock_config
        mock_orpheus_config_class.get_instance.return_value = Mock(
            mqtt=Mock(broker_host="localhost", broker_port=1883)
        )

        agent = BirdDetectionAgent()
        agent.detection_db = Mock()

        event = Detection(
            event_id="bird_det_tax_001",
            timestamp=datetime(2025, 12, 5, 12, 0, 0, tzinfo=timezone.utc),
            detection_type="species.detected",
            channel=1,
            audio_clip_path="/data/test.flac",
            source_event_id="audio_motion_tax_001",
            metadata={"model_version": "BirdNET_V2.4", "inference_time_ms": 100},
        )

        detections = [
            {
                "species_code": "corvus",
                "species_scientific": "Corvus brachyrhynchos",
                "species_common": "American Crow",
                "confidence": 0.92,
                "start_time": 0.0,
                "end_time": 3.0,
            }
        ]

        agent._store_detections(event, detections)
        saved = agent.detection_db.save.call_args[0][0]
        assert saved.taxonomy is not None
        assert saved.taxonomy.namespace == "ioc"
        assert saved.taxonomy.id == "Corvus brachyrhynchos"
        assert saved.taxonomy.common_name == "American Crow"
        # The species_scientific field is also captured in metadata for back-compat.
        assert saved.metadata.get("species_scientific") == "Corvus brachyrhynchos"

    @patch("orpheus_agent_bird_detection.main.load_config")
    @patch("orpheus_agent_bird_detection.main.OrpheusConfig")
    def test_store_detections_taxonomy_is_none_without_scientific(
        self, mock_orpheus_config_class: Mock, mock_load_config: Mock, mock_config: Mock
    ) -> None:
        """Back-compat: legacy detection dicts without species_scientific
        still produce a valid Detection — taxonomy is just None."""
        mock_load_config.return_value = mock_config
        mock_orpheus_config_class.get_instance.return_value = Mock(
            mqtt=Mock(broker_host="localhost", broker_port=1883)
        )

        agent = BirdDetectionAgent()
        agent.detection_db = Mock()

        event = Detection(
            event_id="bird_det_legacy_001",
            timestamp=datetime(2025, 12, 5, 12, 0, 0, tzinfo=timezone.utc),
            detection_type="species.detected",
            channel=1,
            audio_clip_path="/data/test.flac",
            source_event_id="audio_motion_legacy_001",
            metadata={"model_version": "BirdNET_V2.4", "inference_time_ms": 100},
        )

        # No species_scientific — legacy fixture shape.
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
        saved = agent.detection_db.save.call_args[0][0]
        assert saved.taxonomy is None


class TestBirdDetectionShadowPublish:
    """§3 event-sourcing shadow: each persisted bird detection is mirrored to the
    durable domain stream, keyed by event_id. Off by default — the default path is
    byte-identical (no stream_publish). Mirrors the audio-motion shadow tests."""

    @pytest.fixture
    def mock_config(self) -> Mock:
        config = Mock()
        config.model_path = "/fake/model.onnx"
        config.confidence_threshold = 0.5
        config.location_lat = 42.5
        config.location_lon = -83.5
        return config

    def _make_event(self) -> Detection:
        return Detection(
            event_id="bird_det_shadow_001",
            timestamp=datetime(2025, 12, 5, 12, 0, 0, tzinfo=timezone.utc),
            detection_type="species.detected",
            channel=1,
            audio_clip_path="/data/test.flac",
            source_event_id="audio_motion_shadow_001",
            metadata={"model_version": "BirdNET_V2.4", "inference_time_ms": 145},
        )

    @staticmethod
    def _detections() -> list[dict]:
        return [
            {
                "species_code": "amecro",
                "species_common": "American Crow",
                "species_scientific": "Corvus brachyrhynchos",
                "confidence": 0.87,
                "start_time": 0.5,
                "end_time": 1.2,
            }
        ]

    @patch("orpheus_agent_bird_detection.main.load_config")
    @patch("orpheus_agent_bird_detection.main.OrpheusConfig")
    def test_no_shadow_publish_by_default(
        self, mock_orpheus_config_class: Mock, mock_load_config: Mock, mock_config: Mock
    ) -> None:
        """Default (shadow off): stream_publish is never called — byte-identical."""
        mock_load_config.return_value = mock_config
        mock_orpheus_config_class.get_instance.return_value = Mock(
            mqtt=Mock(broker_host="localhost", broker_port=1883)
        )

        agent = BirdDetectionAgent()
        agent.detection_db = Mock()
        agent.bus = Mock()
        # _shadow_publish defaults to False (set in __init__).

        agent._store_detections(self._make_event(), self._detections())

        agent.detection_db.save.assert_called_once()
        agent.bus.stream_publish.assert_not_called()

    @patch("orpheus_agent_bird_detection.main.load_config")
    @patch("orpheus_agent_bird_detection.main.OrpheusConfig")
    def test_shadow_publishes_to_stream_keyed_by_event_id(
        self, mock_orpheus_config_class: Mock, mock_load_config: Mock, mock_config: Mock
    ) -> None:
        """Shadow on: the persisted detection is mirrored to the durable stream with
        Nats-Msg-Id == the SAME event_id that was saved (dedup-able)."""
        mock_load_config.return_value = mock_config
        mock_orpheus_config_class.get_instance.return_value = Mock(
            mqtt=Mock(broker_host="localhost", broker_port=1883)
        )

        agent = BirdDetectionAgent()
        agent.detection_db = Mock()
        agent.bus = Mock()
        agent._shadow_publish = True

        agent._store_detections(self._make_event(), self._detections())

        saved = agent.detection_db.save.call_args[0][0]
        agent.bus.stream_publish.assert_called_once()
        sp = agent.bus.stream_publish.call_args
        # The dedicated shadow subject — never the live topic (double-delivery guard).
        assert sp.args[0] == "orpheus/domain/detection/bird/events"
        assert sp.kwargs["msg_id"] == saved.event_id
        assert sp.args[1]["event_id"] == saved.event_id  # same payload identity

    @patch("orpheus_agent_bird_detection.main.ensure_domain_stream", return_value=True)
    @patch("orpheus_agent_bird_detection.main.load_config")
    @patch("orpheus_agent_bird_detection.main.OrpheusConfig")
    def test_on_started_refreshes_health_when_shadow_active(
        self,
        mock_orpheus_config_class: Mock,
        mock_load_config: Mock,
        mock_ensure: Mock,
        mock_config: Mock,
    ) -> None:
        """The base publishes startup health BEFORE on_started, so it always says
        shadow: false. When the shadow comes up, on_started refreshes health once
        so the true state is visible without waiting a heartbeat."""
        import asyncio  # noqa: PLC0415

        mock_load_config.return_value = mock_config
        mock_orpheus_config_class.get_instance.return_value = Mock(
            mqtt=Mock(broker_host="localhost", broker_port=1883)
        )

        agent = BirdDetectionAgent()
        agent.bus = Mock()

        asyncio.run(agent.on_started())

        mock_ensure.assert_called_once_with(agent.bus, agent.orpheus_config)
        topic, payload = agent.bus.publish.call_args[0]
        assert topic == agent.identity.health_topic
        assert payload["event_sourcing_shadow"] is True

    @patch("orpheus_agent_bird_detection.main.ensure_domain_stream", return_value=False)
    @patch("orpheus_agent_bird_detection.main.load_config")
    @patch("orpheus_agent_bird_detection.main.OrpheusConfig")
    def test_on_started_no_health_refresh_when_shadow_off(
        self,
        mock_orpheus_config_class: Mock,
        mock_load_config: Mock,
        mock_ensure: Mock,
        mock_config: Mock,
    ) -> None:
        """Default (shadow off): no extra publish — startup health already said
        false, so behavior stays byte-identical."""
        import asyncio  # noqa: PLC0415

        mock_load_config.return_value = mock_config
        mock_orpheus_config_class.get_instance.return_value = Mock(
            mqtt=Mock(broker_host="localhost", broker_port=1883)
        )

        agent = BirdDetectionAgent()
        agent.bus = Mock()

        asyncio.run(agent.on_started())

        mock_ensure.assert_called_once_with(agent.bus, agent.orpheus_config)
        agent.bus.publish.assert_not_called()
