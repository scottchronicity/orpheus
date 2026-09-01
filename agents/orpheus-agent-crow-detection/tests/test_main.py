"""Tests for crow detection agent main module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

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
        assert agent.bus is None
        assert agent.embedder is None
        assert agent.classifier is None
        assert agent.detection_db is None
        assert agent.events_processed == 0
        assert agent.detections_found == 0

    @patch("orpheus_agent_crow_detection.main.load_config")
    @patch("orpheus_agent_crow_detection.main.OrpheusConfig.get_instance")
    def test_health_payload_surfaces_shadow_state(
        self, mock_get_instance: MagicMock, mock_load_config: MagicMock
    ) -> None:
        """The online health payload reports whether the event-sourcing shadow is
        recording, so Diagnostics can show a silent self-disable. Off by default."""
        mock_get_instance.return_value = MagicMock()
        mock_load_config.return_value = MagicMock()
        agent = CrowDetectionAgent()

        assert agent.health_payload("startup")["event_sourcing_shadow"] is False
        assert agent.health_payload("heartbeat")["event_sourcing_shadow"] is False
        agent._shadow_publish = True
        assert agent.health_payload("heartbeat")["event_sourcing_shadow"] is True
        # shutdown is an offline subset — no shadow key
        assert "event_sourcing_shadow" not in agent.health_payload("shutdown")

    @patch("orpheus_agent_crow_detection.main.load_config")
    @patch("orpheus_agent_crow_detection.main.OrpheusConfig.get_instance")
    def test_health_payload_surfaces_resolved_device(
        self, mock_get_instance: MagicMock, mock_load_config: MagicMock
    ) -> None:
        """The online health payload carries the RESOLVED torch device (additive
        key) so a silent CPU fallback on the Jetson is visible beyond one startup
        log line. None until on_setup loads the models."""
        mock_get_instance.return_value = MagicMock()
        mock_load_config.return_value = MagicMock()
        agent = CrowDetectionAgent()

        assert agent.health_payload("startup")["device"] is None
        agent._resolved_device = "cpu"
        assert agent.health_payload("startup")["device"] == "cpu"
        assert agent.health_payload("heartbeat")["device"] == "cpu"
        # shutdown is an offline subset — no device key
        assert "device" not in agent.health_payload("shutdown")

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
        agent.bus = mock_mqtt

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
        agent.bus = mock_mqtt

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

    @patch("orpheus_agent_crow_detection.main.setup_logging")
    @patch("orpheus_agent_crow_detection.main.OrpheusConfig.get_instance")
    @patch("orpheus_agent_crow_detection.main.load_config")
    @patch("orpheus_agent_crow_detection.main.asyncio.run")
    def test_main_entry_point(
        self,
        mock_asyncio_run: MagicMock,
        mock_load_config: MagicMock,
        mock_get_instance: MagicMock,
        mock_setup_logging: MagicMock,
    ) -> None:
        """Test main entry point function."""
        mock_config = MagicMock()
        mock_load_config.return_value = mock_config
        mock_orpheus_config = MagicMock()
        mock_get_instance.return_value = mock_orpheus_config

        main()

        # Logging is configured in main(), BEFORE the Actor's enabled() gate —
        # a disabled agent (on_setup never runs) still logs through the
        # configured handlers.
        mock_setup_logging.assert_called_once_with(
            "orpheus-agent-crow-detection", level="INFO"
        )
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
        agent.bus = MagicMock()
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
        agent.bus = MagicMock()
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


class TestAudioEventsHandler:
    """The cross-classifier-identity extension that lets crow-detection
    pick up corvid signals from audio-events (PANNs SED) as well as
    from BirdNET."""

    @patch("orpheus_agent_crow_detection.main.OrpheusConfig.get_instance")
    @patch("orpheus_agent_crow_detection.main.load_config")
    def test_ignores_non_corvid_audioset_tag(
        self, mock_load_config: MagicMock, mock_get_instance: MagicMock
    ) -> None:
        """A "Dog" AudioSet tag shouldn't trigger crow analysis."""
        mock_load_config.return_value = MagicMock()
        mock_get_instance.return_value = MagicMock()
        agent = CrowDetectionAgent()
        with patch.object(agent, "_process_audio_file") as mock_process:
            agent._on_audio_events_event(
                "orpheus/detection/audio/events",
                {
                    "event_id": "ae-dog",
                    "timestamp": "2026-01-01T12:00:00+00:00",
                    "detection_type": "audio.classified",
                    "audio_clip_path": "/data/clip.flac",
                    "taxonomy": {"namespace": "audioset", "id": "/m/0bt9lr"},
                    "metadata": {},
                },
            )
        mock_process.assert_not_called()

    @patch("orpheus_agent_crow_detection.main.Path.exists")
    @patch("orpheus_agent_crow_detection.main.OrpheusConfig.get_instance")
    @patch("orpheus_agent_crow_detection.main.load_config")
    def test_corvid_audioset_tag_triggers_processing(
        self,
        mock_load_config: MagicMock,
        mock_get_instance: MagicMock,
        mock_exists: MagicMock,
    ) -> None:
        """AudioSet Crow (/m/04s8yn) triggers _process_audio_file."""
        mock_load_config.return_value = MagicMock()
        mock_get_instance.return_value = MagicMock()
        mock_exists.return_value = True
        agent = CrowDetectionAgent()
        with patch.object(agent, "_process_audio_file") as mock_process:
            agent._on_audio_events_event(
                "orpheus/detection/audio/events",
                {
                    "event_id": "ae-crow",
                    "timestamp": "2026-01-01T12:00:00+00:00",
                    "detection_type": "audio.classified",
                    "audio_clip_path": "/data/clip.flac",
                    "source_event_id": "am-root",
                    "root_event_id": "am-root",
                    "channel": 1,
                    "confidence": 0.85,
                    "taxonomy": {
                        "namespace": "audioset",
                        "id": "/m/04s8yn",
                        "common_name": "Crow",
                    },
                    "intervals": [
                        {"start_seconds": 0.5, "end_seconds": 2.8, "confidence": 0.85},
                    ],
                    "metadata": {},
                },
            )
        mock_process.assert_called_once()
        # source_event should include the synthesized corvid_detection +
        # propagated root_event_id.
        call_args = mock_process.call_args
        source_event = call_args[0][1]
        assert source_event["root_event_id"] == "am-root"
        assert len(source_event["corvid_detections"]) == 1
        assert source_event["corvid_detections"][0]["_source"] == "audio_events"
        assert source_event["corvid_detections"][0]["is_corvid"] is True

    @patch("orpheus_agent_crow_detection.main.Path.exists")
    @patch("orpheus_agent_crow_detection.main.OrpheusConfig.get_instance")
    @patch("orpheus_agent_crow_detection.main.load_config")
    def test_dedup_skips_recently_processed_clip(
        self,
        mock_load_config: MagicMock,
        mock_get_instance: MagicMock,
        mock_exists: MagicMock,
    ) -> None:
        """If BirdNET already triggered crow-tools on this clip,
        audio-events shouldn't double-process."""
        mock_load_config.return_value = MagicMock()
        mock_get_instance.return_value = MagicMock()
        mock_exists.return_value = True
        agent = CrowDetectionAgent()
        # Simulate: BirdNET already processed this clip 1s ago.
        agent._mark_processed("/data/clip.flac")
        with patch.object(agent, "_process_audio_file") as mock_process:
            agent._on_audio_events_event(
                "orpheus/detection/audio/events",
                {
                    "event_id": "ae-crow-2",
                    "timestamp": "2026-01-01T12:00:00+00:00",
                    "detection_type": "audio.classified",
                    "audio_clip_path": "/data/clip.flac",
                    "taxonomy": {"namespace": "audioset", "id": "/m/04s8yn"},
                    "metadata": {},
                },
            )
        mock_process.assert_not_called()

    @patch("orpheus_agent_crow_detection.main.OrpheusConfig.get_instance")
    @patch("orpheus_agent_crow_detection.main.load_config")
    def test_ignores_non_audioset_taxonomy(
        self, mock_load_config: MagicMock, mock_get_instance: MagicMock
    ) -> None:
        """A taxonomy ref in IOC namespace shouldn't trigger this handler
        (BirdNET path handles those)."""
        mock_load_config.return_value = MagicMock()
        mock_get_instance.return_value = MagicMock()
        agent = CrowDetectionAgent()
        with patch.object(agent, "_process_audio_file") as mock_process:
            agent._on_audio_events_event(
                "orpheus/detection/audio/events",
                {
                    "event_id": "ae-bird",
                    "timestamp": "2026-01-01T12:00:00+00:00",
                    "detection_type": "audio.classified",
                    "audio_clip_path": "/data/clip.flac",
                    "taxonomy": {
                        "namespace": "ioc",
                        "id": "Corvus brachyrhynchos",
                    },
                    "metadata": {},
                },
            )
        mock_process.assert_not_called()


class TestIntervalsFromCorvidDetections:
    """Tests for the static helper that converts BirdNET corvid windows into
    TemporalIntervals on the emitted Detection per ADR 0011 §4.5."""

    def test_extracts_windows_from_single_species(self) -> None:
        corvids = [
            {
                "species_code": "corvus",
                "windows": [
                    {"start_time": 0.0, "end_time": 3.0, "confidence": 0.8},
                    {"start_time": 6.0, "end_time": 9.0, "confidence": 0.6},
                ],
            }
        ]
        intervals = CrowDetectionAgent._intervals_from_corvid_detections(corvids)
        assert len(intervals) == 2
        assert intervals[0].start_seconds == 0.0
        assert intervals[0].end_seconds == 3.0
        assert intervals[0].confidence == 0.8
        assert intervals[1].confidence == 0.6

    def test_falls_back_to_top_level_start_end(self) -> None:
        """Legacy detections without ``windows`` still get one interval from
        the top-level ``start_time``/``end_time``."""
        corvids = [
            {
                "species_code": "corvus",
                "confidence": 0.7,
                "start_time": 2.0,
                "end_time": 5.0,
            }
        ]
        intervals = CrowDetectionAgent._intervals_from_corvid_detections(corvids)
        assert len(intervals) == 1
        assert intervals[0].start_seconds == 2.0
        assert intervals[0].end_seconds == 5.0
        assert intervals[0].confidence == 0.7

    def test_merges_multiple_corvid_species(self) -> None:
        """When both American Crow and Common Raven fire in the same clip,
        all their windows are concatenated and sorted by start time."""
        corvids = [
            {
                "species_code": "corvus",
                "species_common": "American Crow",
                "windows": [
                    {"start_time": 5.0, "end_time": 8.0, "confidence": 0.9},
                ],
            },
            {
                "species_code": "corvus",
                "species_common": "Common Raven",
                "windows": [
                    {"start_time": 0.0, "end_time": 3.0, "confidence": 0.7},
                ],
            },
        ]
        intervals = CrowDetectionAgent._intervals_from_corvid_detections(corvids)
        assert len(intervals) == 2
        # Sorted by start_seconds.
        assert intervals[0].start_seconds == 0.0
        assert intervals[1].start_seconds == 5.0

    def test_empty_input_returns_empty_list(self) -> None:
        assert CrowDetectionAgent._intervals_from_corvid_detections([]) == []

    def test_skips_malformed_windows(self) -> None:
        """A window missing start_time or end_time is skipped, not crashed on."""
        corvids = [
            {
                "species_code": "corvus",
                "windows": [
                    {"start_time": 0.0, "end_time": 3.0, "confidence": 0.8},
                    {"confidence": 0.5},  # malformed
                ],
            }
        ]
        intervals = CrowDetectionAgent._intervals_from_corvid_detections(corvids)
        assert len(intervals) == 1
        assert intervals[0].start_seconds == 0.0


class TestEventSourcingShadow:
    """The crow agent OWNS orpheus/detection/crow/events, so it shadow-publishes
    each saved detection to the durable domain stream (ADR 0012 / event-sourcing
    determinism contract). Off by default; nats-only; keyed by event_id."""

    @staticmethod
    @patch("orpheus_agent_crow_detection.main.sf.read")
    @patch("orpheus_agent_crow_detection.main.CrowDetectionAgent._generate_event_id")
    @patch("orpheus_agent_crow_detection.main.OrpheusConfig.get_instance")
    @patch("orpheus_agent_crow_detection.main.load_config")
    def _emit_one_detection(
        mock_load_config: MagicMock,
        mock_get_instance: MagicMock,
        mock_generate_id: MagicMock,
        mock_sf_read: MagicMock,
        *,
        shadow: bool,
    ) -> MagicMock:
        """Drive a single positive detection through the emit path (publish +
        save + shadow) and return the Mock bus for assertions. Mirrors
        ``test_process_audio_file_positive_detection``."""
        mock_config = MagicMock()
        mock_config.embedder_sample_rate = 16000
        mock_config.quality_threshold = 0.5
        mock_load_config.return_value = mock_config
        mock_get_instance.return_value = MagicMock()

        agent = CrowDetectionAgent()
        # Set the shadow flag the way on_started would once enabled.
        agent._shadow_publish = shadow

        mock_embedder = MagicMock()
        mock_embedder.generate_embedding.return_value = np.random.randn(1, 768).astype(
            np.float32
        )
        agent.embedder = mock_embedder

        mock_classifier = MagicMock()
        mock_classifier.classify.return_value = CrowDetectionResult(
            is_crow=True,
            quality_score=0.85,
            species="american_crow",
            call_type="caw",
            attributes={"alert": 0.9, "age": "adult"},
        )
        agent.classifier = mock_classifier

        mock_bus = MagicMock()
        agent.bus = mock_bus
        agent.detection_db = MagicMock()

        mock_sf_read.return_value = (np.random.randn(48000).astype(np.float32), 48000)
        mock_generate_id.return_value = "crow_det_test_shadow_001"

        agent._process_audio_file(
            Path("/path/to/audio.flac"),
            {"event_id": "audio_motion_001", "channel_id": "1"},
        )
        return mock_bus

    def test_no_shadow_stream_publish_by_default(self) -> None:
        """Default (shadow off): stream_publish is never called — byte-identical."""
        mock_bus = self._emit_one_detection(shadow=False)
        mock_bus.publish.assert_called_once()
        mock_bus.stream_publish.assert_not_called()

    def test_shadow_publishes_to_stream_keyed_by_event_id(self) -> None:
        """Shadow on: the saved detection is mirrored to the durable stream with
        msg_id == the SAME event_id that was published + saved (dedup-able)."""
        mock_bus = self._emit_one_detection(shadow=True)
        mock_bus.stream_publish.assert_called_once()
        sp = mock_bus.stream_publish.call_args
        # The dedicated shadow subject — never the live topic (double-delivery guard).
        assert sp.args[0] == "orpheus/domain/detection/crow/events"
        assert sp.kwargs["msg_id"] == "crow_det_test_shadow_001"
        assert sp.args[1]["event_id"] == "crow_det_test_shadow_001"

    @patch("orpheus_agent_crow_detection.main.ensure_domain_stream", return_value=True)
    @patch("orpheus_agent_crow_detection.main.OrpheusConfig.get_instance")
    @patch("orpheus_agent_crow_detection.main.load_config")
    def test_on_started_refreshes_health_when_shadow_active(
        self,
        mock_load_config: MagicMock,
        mock_get_instance: MagicMock,
        _mock_ensure: MagicMock,
    ) -> None:
        """The base publishes startup health BEFORE on_started, so it always says
        shadow: false. When the shadow comes up, on_started refreshes health once
        so the true state is visible without waiting a heartbeat."""
        import asyncio  # noqa: PLC0415

        mock_load_config.return_value = MagicMock()
        mock_get_instance.return_value = MagicMock()
        agent = CrowDetectionAgent()
        agent.bus = MagicMock()

        asyncio.run(agent.on_started())

        topic, payload = agent.bus.publish.call_args[0]
        assert topic == agent.identity.health_topic
        assert payload["event_sourcing_shadow"] is True

    @patch("orpheus_agent_crow_detection.main.ensure_domain_stream", return_value=False)
    @patch("orpheus_agent_crow_detection.main.OrpheusConfig.get_instance")
    @patch("orpheus_agent_crow_detection.main.load_config")
    def test_on_started_no_health_refresh_when_shadow_off(
        self,
        mock_load_config: MagicMock,
        mock_get_instance: MagicMock,
        _mock_ensure: MagicMock,
    ) -> None:
        """Default (shadow off): no extra publish — startup health already said
        false, so behavior stays byte-identical."""
        import asyncio  # noqa: PLC0415

        mock_load_config.return_value = MagicMock()
        mock_get_instance.return_value = MagicMock()
        agent = CrowDetectionAgent()
        agent.bus = MagicMock()

        asyncio.run(agent.on_started())

        agent.bus.publish.assert_not_called()
