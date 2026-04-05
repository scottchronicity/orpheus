"""Tests for the event correlator clustering logic."""

from __future__ import annotations

import asyncio
import threading
from datetime import datetime, timezone
from typing import Any
from unittest.mock import Mock, patch

import pytest
from orpheus_common.detection import Detection, DetectionDB
from orpheus_common.events import SpatiotemporalContext

from orpheus_agent_event_correlator.cluster_manager import (
    ClusterManager,
    Observation,
    TemporalCluster,
)
from orpheus_agent_event_correlator.main import EventCorrelatorAgent


class TestTemporalCluster:
    """Tests for the TemporalCluster class."""

    def test_add_observation(self) -> None:
        """Adding an observation updates the cluster."""
        cluster = TemporalCluster("amecro")
        obs = Observation(
            species_code="amecro",
            common_name="American Crow",
            confidence=0.85,
            event_id="evt-1",
            source_event_id="src-1",
            sensor_id="mic-1",
            clip_path="/data/clip1.flac",
            context={"lat": 40.7, "lon": -74.0},
        )
        cluster.add_observation(obs)
        assert len(cluster.observations) == 1
        assert cluster.max_confidence == 0.85
        assert cluster.common_name == "American Crow"

    def test_max_confidence(self) -> None:
        """max_confidence returns highest confidence across observations."""
        cluster = TemporalCluster("amecro")
        for conf in [0.5, 0.98, 0.7]:
            obs = Observation(
                species_code="amecro",
                common_name="American Crow",
                confidence=conf,
                event_id="evt",
                source_event_id=None,
                sensor_id="mic-1",
                clip_path=None,
                context=None,
            )
            cluster.add_observation(obs)
        assert cluster.max_confidence == 0.98

    def test_build_entity_event(self) -> None:
        """build_entity_event produces correct EntityEvent structure."""
        cluster = TemporalCluster("amecro")
        obs1 = Observation(
            species_code="amecro",
            common_name="American Crow",
            confidence=0.85,
            event_id="evt-1",
            source_event_id="src-1",
            sensor_id="mic-1",
            clip_path="/data/clip1.flac",
            context={"lat": 40.0, "lon": -74.0},
        )
        obs2 = Observation(
            species_code="amecro",
            common_name="American Crow",
            confidence=0.92,
            event_id="evt-2",
            source_event_id="src-2",
            sensor_id="mic-2",
            clip_path="/data/clip2.flac",
            context={"lat": 42.0, "lon": -76.0},
        )
        cluster.add_observation(obs1)
        cluster.add_observation(obs2)

        event = cluster.build_entity_event()

        assert event["species_code"] == "amecro"
        assert event["common_name"] == "American Crow"
        assert event["confidence"] == 0.92
        assert len(event["evidence"]) == 2
        # Average lat/lon
        assert event["context"]["lat"] == pytest.approx(41.0)
        assert event["context"]["lon"] == pytest.approx(-75.0)
        # Entity ID should be a UUID
        assert len(event["entity_id"]) > 0
        assert "timestamp" in event

    def test_build_entity_event_no_context(self) -> None:
        """build_entity_event works when observations have no context."""
        cluster = TemporalCluster("amerob")
        obs = Observation(
            species_code="amerob",
            common_name="American Robin",
            confidence=0.75,
            event_id="evt-1",
            source_event_id=None,
            sensor_id="",
            clip_path=None,
            context=None,
        )
        cluster.add_observation(obs)
        event = cluster.build_entity_event()

        assert event["species_code"] == "amerob"
        assert "lat" not in event["context"]
        assert "lon" not in event["context"]


class TestClusterManager:
    """Tests for the ClusterManager class."""

    def test_process_observation_creates_cluster(self) -> None:
        """Processing an observation creates a new cluster."""
        emitted: list[dict[str, Any]] = []
        manager = ClusterManager(window_seconds=3.0, on_entity_ready=emitted.append)

        obs = Observation(
            species_code="amecro",
            common_name="American Crow",
            confidence=0.85,
            event_id="evt-1",
            source_event_id="src-1",
            sensor_id="mic-1",
            clip_path="/data/clip1.flac",
            context=None,
        )
        manager.process_observation(obs)

        assert "amecro" in manager._clusters
        assert len(manager._clusters["amecro"].observations) == 1

    def test_flush_all_emits_events(self) -> None:
        """flush_all closes all clusters and returns EntityEvents."""
        manager = ClusterManager(window_seconds=3.0)

        obs1 = Observation(
            species_code="amecro",
            common_name="American Crow",
            confidence=0.85,
            event_id="evt-1",
            source_event_id=None,
            sensor_id="mic-1",
            clip_path=None,
            context=None,
        )
        obs2 = Observation(
            species_code="amerob",
            common_name="American Robin",
            confidence=0.70,
            event_id="evt-2",
            source_event_id=None,
            sensor_id="mic-2",
            clip_path=None,
            context=None,
        )
        manager.process_observation(obs1)
        manager.process_observation(obs2)

        events = manager.flush_all()

        assert len(events) == 2
        species = {e["species_code"] for e in events}
        assert species == {"amecro", "amerob"}
        assert len(manager._clusters) == 0


class TestMultiSpeciesScenario:
    """Scenario A: One message with multiple sub-detections produces separate EntityEvents."""

    @patch("orpheus_agent_event_correlator.main.OrpheusConfig")
    def test_one_message_two_birds_two_entity_events(
        self,
        mock_orpheus_config_class: Mock,
    ) -> None:
        """A single detection with 2 species in metadata['detections'] should
        produce 2 separate EntityEvents (one per species)."""
        mock_orpheus_config_class.get_instance.return_value = Mock(
            mqtt=Mock(broker_host="localhost", broker_port=1883)
        )

        agent = EventCorrelatorAgent(window_seconds=3.0)
        agent.mqtt_client = Mock()

        emitted_events: list[dict[str, Any]] = []

        def capture_entity(event: dict[str, Any]) -> None:
            emitted_events.append(event)

        agent.cluster_manager = ClusterManager(
            window_seconds=3.0,
            on_entity_ready=capture_entity,
        )

        # Simulate a bird detection with 2 species in sub-detections
        # Use the actual Pydantic Detection model to generate the payload,
        # ensuring the test breaks if the schema changes in orpheus-common.
        bird_detection = Detection(
            event_id="bird-det-001",
            timestamp=datetime.now(timezone.utc),
            detection_type="species.detected",
            channel=1,
            audio_clip_path="/data/orpheus/audio/clip1.flac",
            source_event_id="audio-motion-001",
            context=SpatiotemporalContext(
                lat=40.7128,
                lon=-74.0060,
                sensor_id="mic-1",
            ),
            metadata={
                "detections": [
                    {
                        "species_code": "amecro",
                        "species_common": "American Crow",
                        "confidence": 0.87,
                        "start_time": 0.0,
                        "end_time": 3.0,
                    },
                    {
                        "species_code": "amerob",
                        "species_common": "American Robin",
                        "confidence": 0.72,
                        "start_time": 0.5,
                        "end_time": 3.0,
                    },
                ],
                "model_version": "BirdNET_V2.4",
            },
        )
        payload: dict[str, Any] = bird_detection.model_dump(mode="json")

        agent._on_detection_event("orpheus/detection/bird/events", payload)

        # Flush clusters to emit the events
        remaining = agent.cluster_manager.flush_all()
        for evt in remaining:
            emitted_events.append(evt)

        # Should produce 2 EntityEvents - one for crow, one for robin
        assert len(emitted_events) == 2
        species_codes = {e["species_code"] for e in emitted_events}
        assert species_codes == {"amecro", "amerob"}

        # Verify each event has 1 evidence item
        for event in emitted_events:
            assert len(event["evidence"]) == 1
            assert event["evidence"][0]["event_id"] == "bird-det-001"
            assert event["evidence"][0]["source_event_id"] == "audio-motion-001"


class TestMultiSensorScenario:
    """Scenario B: Multiple messages for same species from different sensors
    within the window produce a single EntityEvent."""

    @patch("orpheus_agent_event_correlator.main.OrpheusConfig")
    def test_three_mics_one_crow_one_entity_event(
        self,
        mock_orpheus_config_class: Mock,
    ) -> None:
        """3 detection messages for 'American Crow' from 3 different microphones
        within 1 second should produce 1 EntityEvent with 3 evidence items."""
        mock_orpheus_config_class.get_instance.return_value = Mock(
            mqtt=Mock(broker_host="localhost", broker_port=1883)
        )

        agent = EventCorrelatorAgent(window_seconds=3.0)
        agent.mqtt_client = Mock()

        emitted_events: list[dict[str, Any]] = []

        def capture_entity(event: dict[str, Any]) -> None:
            emitted_events.append(event)

        agent.cluster_manager = ClusterManager(
            window_seconds=3.0,
            on_entity_ready=capture_entity,
        )

        # Send 3 detection messages from 3 different mics
        for i in range(1, 4):
            payload: dict[str, Any] = {
                "event_id": f"bird-det-{i:03d}",
                "event_timestamp": datetime.now(timezone.utc).isoformat(),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "detection_type": "species.detected",
                "channel": i,
                "species_code": "amecro",
                "species_common": "American Crow",
                "confidence": 0.80 + i * 0.05,
                "audio_clip_path": f"/data/orpheus/audio/clip{i}.flac",
                "source_event_id": f"audio-motion-{i:03d}",
                "context": {
                    "lat": 40.7128,
                    "lon": -74.0060,
                    "sensor_id": f"mic-{i}",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
                "metadata": {},
            }
            agent._on_detection_event(
                "orpheus/detection/bird/events",
                payload,
            )

        # Flush to emit
        remaining = agent.cluster_manager.flush_all()
        for evt in remaining:
            emitted_events.append(evt)

        # Should produce exactly 1 EntityEvent
        assert len(emitted_events) == 1

        event = emitted_events[0]
        assert event["species_code"] == "amecro"
        assert event["common_name"] == "American Crow"
        # Max confidence should be 0.80 + 3 * 0.05 = 0.95
        assert event["confidence"] == pytest.approx(0.95)
        # Should have 3 evidence items
        assert len(event["evidence"]) == 3
        # Verify sensor IDs
        sensor_ids = {e["sensor_id"] for e in event["evidence"]}
        assert sensor_ids == {"mic-1", "mic-2", "mic-3"}


class TestEventFiltering:
    """Tests for event filtering logic."""

    @patch("orpheus_agent_event_correlator.main.OrpheusConfig")
    def test_audio_motion_events_are_ignored(
        self,
        mock_orpheus_config_class: Mock,
    ) -> None:
        """audio.motion detection type should be ignored."""
        mock_orpheus_config_class.get_instance.return_value = Mock(
            mqtt=Mock(broker_host="localhost", broker_port=1883)
        )

        agent = EventCorrelatorAgent(window_seconds=3.0)
        agent.mqtt_client = Mock()
        agent.cluster_manager = ClusterManager(window_seconds=3.0)

        payload: dict[str, Any] = {
            "event_id": "audio-motion-001",
            "event_timestamp": datetime.now(timezone.utc).isoformat(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "detection_type": "audio.motion",
            "channel": 1,
            "audio_clip_path": "/data/clip.flac",
            "metadata": {},
        }

        agent._on_detection_event("orpheus/detection/audio/events", payload)

        assert agent.events_ignored == 1
        assert len(agent.cluster_manager._clusters) == 0


class TestEntityPersistence:
    """Tests that the correlator persists entities to the database."""

    @patch("orpheus_agent_event_correlator.main.OrpheusConfig")
    def test_persist_entity_saves_to_db(
        self,
        mock_orpheus_config_class: Mock,
        tmp_path: Any,
    ) -> None:
        """_persist_entity should save the entity to the database."""

        mock_orpheus_config_class.get_instance.return_value = Mock(
            mqtt=Mock(broker_host="localhost", broker_port=1883)
        )

        agent = EventCorrelatorAgent(window_seconds=3.0)
        agent.db = DetectionDB(db_path=tmp_path / "test.db")

        entity_event: dict[str, Any] = {
            "entity_id": "ent-persist-001",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "species_code": "amecro",
            "common_name": "American Crow",
            "confidence": 0.92,
            "context": {"lat": 40.7, "lon": -74.0},
            "evidence": [
                {
                    "event_id": "det-1",
                    "sensor_id": "mic-1",
                    "confidence": 0.92,
                },
                {
                    "event_id": "det-2",
                    "sensor_id": "mic-2",
                    "confidence": 0.88,
                },
            ],
        }

        agent._persist_entity(entity_event)

        # Verify entity is in the database
        entities = agent.db.get_entities(species="amecro")
        assert len(entities) == 1
        assert entities[0].entity_id == "ent-persist-001"
        assert entities[0].common_name == "American Crow"
        assert len(entities[0].evidence) == 2

    @patch("orpheus_agent_event_correlator.main.OrpheusConfig")
    def test_on_entity_ready_persists_and_publishes(
        self,
        mock_orpheus_config_class: Mock,
        tmp_path: Any,
    ) -> None:
        """_on_entity_ready should persist to DB and publish to MQTT."""

        mock_orpheus_config_class.get_instance.return_value = Mock(
            mqtt=Mock(broker_host="localhost", broker_port=1883)
        )

        agent = EventCorrelatorAgent(window_seconds=3.0)
        agent.db = DetectionDB(db_path=tmp_path / "test.db")
        agent.mqtt_client = Mock()

        entity_event: dict[str, Any] = {
            "entity_id": "ent-ready-001",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "species_code": "amerob",
            "common_name": "American Robin",
            "confidence": 0.85,
            "context": {},
            "evidence": [
                {"event_id": "d1", "sensor_id": "mic-1", "confidence": 0.85},
            ],
        }

        agent._on_entity_ready(entity_event)

        # Should persist
        entities = agent.db.get_entities()
        assert len(entities) == 1
        assert entities[0].species == "amerob"

        # Should publish
        assert agent.mqtt_client.publish.called
        assert agent.entities_emitted == 1


class TestEventFilteringCrow:
    """Tests for crow event filtering logic."""

    @patch("orpheus_agent_event_correlator.main.OrpheusConfig")
    def test_crow_analyzed_events_are_processed(
        self,
        mock_orpheus_config_class: Mock,
    ) -> None:
        """crow.analyzed detection type should be processed."""
        mock_orpheus_config_class.get_instance.return_value = Mock(
            mqtt=Mock(broker_host="localhost", broker_port=1883)
        )

        agent = EventCorrelatorAgent(window_seconds=3.0)
        agent.mqtt_client = Mock()
        agent.cluster_manager = ClusterManager(window_seconds=3.0)

        payload: dict[str, Any] = {
            "event_id": "crow-det-001",
            "event_timestamp": datetime.now(timezone.utc).isoformat(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "detection_type": "crow.analyzed",
            "channel": 1,
            "species_code": "amecro",
            "species_common": "American Crow",
            "confidence": 0.92,
            "audio_clip_path": "/data/crow.flac",
            "source_event_id": "bird-det-001",
            "metadata": {},
        }

        agent._on_detection_event("orpheus/detection/crow/events", payload)

        assert agent.events_ignored == 0
        assert "amecro" in agent.cluster_manager._clusters


class TestTimerBasedExpiration:
    """Tests for timer-based cluster expiration using asyncio event loop."""

    @pytest.mark.asyncio
    async def test_cluster_expires_after_window(self) -> None:
        """Cluster should expire and emit after window_seconds with no new observations."""
        emitted_events: list[dict[str, Any]] = []

        def capture_entity(event: dict[str, Any]) -> None:
            emitted_events.append(event)

        loop = asyncio.get_running_loop()
        manager = ClusterManager(window_seconds=0.1, on_entity_ready=capture_entity)
        manager.set_loop(loop)

        obs = Observation(
            species_code="amecro",
            common_name="American Crow",
            confidence=0.90,
            event_id="evt-1",
            source_event_id="src-1",
            sensor_id="mic-1",
            clip_path="/data/clip1.flac",
            context=None,
        )
        manager.process_observation(obs)

        # Wait for the timer to expire
        await asyncio.sleep(0.2)

        assert len(emitted_events) == 1
        assert emitted_events[0]["species_code"] == "amecro"
        assert len(manager._clusters) == 0

    @pytest.mark.asyncio
    async def test_timer_resets_on_new_observation(self) -> None:
        """Adding a new observation should reset the expiration timer."""
        emitted_events: list[dict[str, Any]] = []

        def capture_entity(event: dict[str, Any]) -> None:
            emitted_events.append(event)

        loop = asyncio.get_running_loop()
        manager = ClusterManager(window_seconds=0.2, on_entity_ready=capture_entity)
        manager.set_loop(loop)

        obs1 = Observation(
            species_code="amecro",
            common_name="American Crow",
            confidence=0.80,
            event_id="evt-1",
            source_event_id="src-1",
            sensor_id="mic-1",
            clip_path="/data/clip1.flac",
            context=None,
        )
        manager.process_observation(obs1)

        # Wait 0.1s (half the window) then add another observation
        await asyncio.sleep(0.1)

        obs2 = Observation(
            species_code="amecro",
            common_name="American Crow",
            confidence=0.95,
            event_id="evt-2",
            source_event_id="src-2",
            sensor_id="mic-2",
            clip_path="/data/clip2.flac",
            context=None,
        )
        manager.process_observation(obs2)

        # At 0.2s total, the original timer would have fired, but it was reset
        await asyncio.sleep(0.15)

        # Should not have emitted yet (timer was reset)
        assert len(emitted_events) == 0

        # Wait for the reset timer to expire
        await asyncio.sleep(0.15)

        # Now it should have emitted with 2 evidence items
        assert len(emitted_events) == 1
        assert len(emitted_events[0]["evidence"]) == 2
        assert emitted_events[0]["confidence"] == pytest.approx(0.95)


class TestThreadSafeScheduling:
    """Tests that process_observation works correctly when called from a background thread."""

    @pytest.mark.asyncio
    async def test_process_observation_from_background_thread(self) -> None:
        """Calling process_observation from a non-event-loop thread should
        still result in the cluster expiring and emitting an EntityEvent."""
        emitted_events: list[dict[str, Any]] = []

        def capture_entity(event: dict[str, Any]) -> None:
            emitted_events.append(event)

        loop = asyncio.get_running_loop()
        manager = ClusterManager(window_seconds=0.1, on_entity_ready=capture_entity)
        manager.set_loop(loop)

        obs = Observation(
            species_code="amecro",
            common_name="American Crow",
            confidence=0.90,
            event_id="evt-thread-1",
            source_event_id="src-1",
            sensor_id="mic-1",
            clip_path="/data/clip1.flac",
            context=None,
        )

        # Call process_observation from a background thread (simulates MQTT thread)
        thread = threading.Thread(target=manager.process_observation, args=(obs,))
        thread.start()
        thread.join()

        # Wait for the timer to expire (3x window to allow for thread scheduling overhead)
        await asyncio.sleep(0.3)

        assert len(emitted_events) == 1
        assert emitted_events[0]["species_code"] == "amecro"
        assert len(manager._clusters) == 0


class TestLegacyBirdNETSchema:
    """Tests that the correlator handles legacy BirdNET payloads with root-level detections."""

    @patch("orpheus_agent_event_correlator.main.OrpheusConfig")
    def test_legacy_root_level_detections(
        self,
        mock_orpheus_config_class: Mock,
    ) -> None:
        """A legacy payload with root-level 'detections' (not in metadata)
        should still be unpacked into observations."""
        mock_orpheus_config_class.get_instance.return_value = Mock(
            mqtt=Mock(broker_host="localhost", broker_port=1883)
        )

        agent = EventCorrelatorAgent(window_seconds=3.0)
        agent.mqtt_client = Mock()

        emitted_events: list[dict[str, Any]] = []

        def capture_entity(event: dict[str, Any]) -> None:
            emitted_events.append(event)

        agent.cluster_manager = ClusterManager(
            window_seconds=3.0,
            on_entity_ready=capture_entity,
        )

        # Legacy BirdNET payload: 'detections' at root level, not in metadata
        legacy_payload: dict[str, Any] = {
            "event_id": "bird-det-legacy-001",
            "event_timestamp": datetime.now(timezone.utc).isoformat(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "detection_type": "species.detected",
            "channel": 1,
            "audio_clip_path": "/data/orpheus/audio/legacy_clip.flac",
            "metadata": {},
            "detections": [
                {
                    "species_code": "amerob",
                    "species_common": "American Robin",
                    "confidence": 0.82,
                    "start_time": 0.0,
                    "end_time": 3.0,
                },
                {
                    "species_code": "houspa",
                    "species_common": "House Sparrow",
                    "confidence": 0.65,
                    "start_time": 1.0,
                    "end_time": 3.0,
                },
            ],
        }

        agent._on_detection_event("orpheus/detection/bird/events", legacy_payload)

        # Flush clusters
        remaining = agent.cluster_manager.flush_all()
        for evt in remaining:
            emitted_events.append(evt)

        # Should produce 2 EntityEvents — one per species
        assert len(emitted_events) == 2
        species_codes = {e["species_code"] for e in emitted_events}
        assert species_codes == {"amerob", "houspa"}

    @patch("orpheus_agent_event_correlator.main.OrpheusConfig")
    def test_malformed_payload_does_not_crash(
        self,
        mock_orpheus_config_class: Mock,
    ) -> None:
        """A completely invalid payload should be logged and ignored, not crash."""
        mock_orpheus_config_class.get_instance.return_value = Mock(
            mqtt=Mock(broker_host="localhost", broker_port=1883)
        )

        agent = EventCorrelatorAgent(window_seconds=3.0)
        agent.mqtt_client = Mock()
        agent.cluster_manager = ClusterManager(window_seconds=3.0)

        # Payload missing required 'timestamp' and 'detection_type'
        bad_payload: dict[str, Any] = {"event_id": "bad-event", "random_field": 42}

        agent._on_detection_event("orpheus/detection/bird/events", bad_payload)

        assert agent.events_ignored == 1
        assert len(agent.cluster_manager._clusters) == 0
