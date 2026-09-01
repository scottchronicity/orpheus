"""Tests for the event correlator clustering logic."""

from __future__ import annotations

import asyncio
import threading
from datetime import datetime, timezone
from typing import Any
from unittest.mock import Mock, patch

import pytest
from orpheus_common.detection import Detection, DetectionDB, same_source
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
        cluster = TemporalCluster()
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
        # Layer 2 refactor: clusters no longer carry a single species_code/
        # common_name. The display_observation property exposes the highest-
        # confidence observation for legacy display purposes.
        display = cluster.display_observation
        assert display is not None
        assert display.common_name == "American Crow"

    def test_max_confidence(self) -> None:
        """max_confidence returns highest confidence across observations."""
        cluster = TemporalCluster()
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
        cluster = TemporalCluster()
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

    def test_flush_all_splits_different_species_into_separate_entities(self) -> None:
        """Source-identity (entity-source-identity.md): a crow and a robin
        in the same window are DIFFERENT sources, so they produce TWO
        Entities — not one "soup" entity. Each entity's evidence is only
        its own source; the other is surfaced under ``also_detected``."""
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

        assert len(events) == 2, "Different species are different sources → two Entities."
        by_species = {e["species_code"]: e for e in events}
        assert set(by_species) == {"amecro", "amerob"}
        # Each entity's evidence is ONLY its own source.
        assert {ev["species_code"] for ev in by_species["amecro"]["evidence"]} == {"amecro"}
        assert {ev["species_code"] for ev in by_species["amerob"]["evidence"]} == {"amerob"}
        # ...and each lists the other as co-occurring context, NOT evidence.
        assert any(a["species_code"] == "amerob" for a in by_species["amecro"]["also_detected"])
        assert any(a["species_code"] == "amecro" for a in by_species["amerob"]["also_detected"])

    def test_same_species_two_mics_merges_into_one_entity(self) -> None:
        """The flip side: the SAME species heard on two mics is ONE source
        → one Entity with two sensors (the honest multi-sensor count)."""
        manager = ClusterManager(window_seconds=3.0)
        for mic, evt in (("mic-1", "e1"), ("mic-2", "e2")):
            manager.process_observation(
                Observation(
                    species_code="amecro",
                    common_name="American Crow",
                    confidence=0.8,
                    event_id=evt,
                    source_event_id=None,
                    sensor_id=mic,
                    clip_path=None,
                    context=None,
                )
            )
        events = manager.flush_all()
        assert len(events) == 1
        assert set(events[0]["event_signature"]["sensor_ids"]) == {"mic-1", "mic-2"}

    def test_disjoint_intervals_same_window_split(self) -> None:
        """Two sounds in one 30s clip at non-overlapping times (a cricket at
        0-9s, a loon at 13.5-16.5s) are different sources → two Entities."""
        manager = ClusterManager(window_seconds=3.0)
        manager.process_observation(
            Observation(
                species_code="insect", common_name="Insect", confidence=0.51,
                event_id="i1", source_event_id="root-1", sensor_id="mic-2",
                clip_path=None, context=None,
                intervals=[{"start_seconds": 0.0, "end_seconds": 9.6}],
            )
        )
        manager.process_observation(
            Observation(
                species_code="loon", common_name="Common Loon", confidence=0.12,
                event_id="l1", source_event_id="root-1", sensor_id="mic-2",
                clip_path=None, context=None,
                intervals=[{"start_seconds": 13.5, "end_seconds": 16.5}],
            )
        )
        events = manager.flush_all()
        assert len(events) == 2, "Non-overlapping sounds in one clip are separate sources."
        assert {e["species_code"] for e in events} == {"insect", "loon"}

    def test_cross_root_disjoint_offsets_merge_same_species(self) -> None:
        """Two mics fire on two SEPARATE audio.motion clips (different
        root_event_ids) within one time window, each hearing the same crow but
        at different clip-relative offsets. The offsets share no t=0 across
        clips, so they must NOT be compared as if they did — same species in one
        window is one source → ONE entity, two sensors. (Before the root gate
        this false-split into two crows.)"""
        manager = ClusterManager(window_seconds=3.0)
        manager.process_observation(
            Observation(
                species_code="amecro", common_name="American Crow", confidence=0.8,
                event_id="a1", source_event_id=None, sensor_id="mic-1",
                clip_path=None, context=None,
                intervals=[{"start_seconds": 0.0, "end_seconds": 3.0}],
                root_event_id="motion-A",
            )
        )
        manager.process_observation(
            Observation(
                species_code="amecro", common_name="American Crow", confidence=0.7,
                event_id="a2", source_event_id=None, sensor_id="mic-2",
                clip_path=None, context=None,
                intervals=[{"start_seconds": 13.5, "end_seconds": 16.5}],
                root_event_id="motion-B",
            )
        )
        events = manager.flush_all()
        assert len(events) == 1, "Same species across two clips in one window is one source."
        assert set(events[0]["event_signature"]["sensor_ids"]) == {"mic-1", "mic-2"}

    def test_same_root_disjoint_offsets_still_split(self) -> None:
        """Boundary: the same two observations but sharing a root_event_id (one
        clip). Now the offsets ARE comparable, and disjoint times split them —
        confirming the gate keys precisely on clip origin and nothing else (same
        clip = unchanged behaviour)."""
        manager = ClusterManager(window_seconds=3.0)
        for evt, mic, iv in (
            ("a1", "mic-1", [{"start_seconds": 0.0, "end_seconds": 3.0}]),
            ("a2", "mic-1", [{"start_seconds": 13.5, "end_seconds": 16.5}]),
        ):
            manager.process_observation(
                Observation(
                    species_code="amecro", common_name="American Crow", confidence=0.8,
                    event_id=evt, source_event_id=None, sensor_id=mic,
                    clip_path=None, context=None, intervals=iv,
                    root_event_id="motion-A",
                )
            )
        events = manager.flush_all()
        assert len(events) == 2, "Disjoint times within ONE clip stay separate sources."

    def test_equivalent_cross_classifier_labels_merge(self) -> None:
        """Cross-classifier same-source: BirdNET 'American Crow' and PANNs
        'Crow' overlapping in time merge into ONE entity via the
        deterministic static bridge — no learned equivalence, no DB, so it
        works identically out of the box on laptop and Jetson."""
        manager = ClusterManager(window_seconds=3.0, is_equivalent=same_source)
        manager.process_observation(
            Observation(
                species_code="corvus", common_name="American Crow", confidence=0.9,
                event_id="b1", source_event_id="root-1", sensor_id="mic-1",
                clip_path=None, context=None,
                intervals=[{"start_seconds": 0.0, "end_seconds": 3.0}],
                taxonomy={"namespace": "ioc", "id": "Corvus brachyrhynchos"},
            )
        )
        manager.process_observation(
            Observation(
                species_code="audioset_x", common_name="Crow", confidence=0.8,
                event_id="p1", source_event_id="root-1", sensor_id="mic-1",
                clip_path=None, context=None,
                intervals=[{"start_seconds": 0.5, "end_seconds": 2.8}],
                taxonomy={"namespace": "audioset", "id": "/m/04s8yn"},
            )
        )
        events = manager.flush_all()
        assert len(events) == 1, "Equivalent labels overlapping in time = one source."
        assert len(events[0]["evidence"]) == 2


class TestMultiSpeciesScenario:
    """Scenario A (Layer 2): one message with multiple sub-detections
    produces ONE EntityEvent with both species as evidence."""

    @patch("orpheus_agent_event_correlator.main.OrpheusConfig")
    def test_one_message_two_birds_splits_into_two_entities(
        self,
        mock_orpheus_config_class: Mock,
    ) -> None:
        """Source-identity: a single bird detection carrying 2 species
        (crow + robin) produces TWO Entities — different sources even
        though they overlap in time on the same clip. Per-source evidence;
        each cross-references the other under ``also_detected``."""
        mock_orpheus_config_class.get_instance.return_value = Mock(
            mqtt=Mock(broker_host="localhost", broker_port=1883)
        )

        agent = EventCorrelatorAgent(window_seconds=3.0)
        agent.bus = Mock()

        emitted_events: list[dict[str, Any]] = []

        def capture_entity(event: dict[str, Any]) -> None:
            emitted_events.append(event)

        agent.cluster_manager = ClusterManager(
            window_seconds=3.0,
            on_entity_ready=capture_entity,
        )

        # Simulate a bird detection with 2 species in sub-detections.
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

        # Flush clusters to emit the events.
        remaining = agent.cluster_manager.flush_all()
        for evt in remaining:
            emitted_events.append(evt)

        # TWO Entities — crow and robin are different sources.
        assert len(emitted_events) == 2
        by_species = {e["species_code"]: e for e in emitted_events}
        assert set(by_species) == {"amecro", "amerob"}
        for sp, ent in by_species.items():
            assert {ev["species_code"] for ev in ent["evidence"]} == {sp}
            for ev in ent["evidence"]:
                assert ev["event_id"] == "bird-det-001"
                assert ev["source_event_id"] == "audio-motion-001"
        # Each lists the other as co-occurring context, not evidence.
        assert any(a["species_code"] == "amerob" for a in by_species["amecro"]["also_detected"])
        assert any(a["species_code"] == "amecro" for a in by_species["amerob"]["also_detected"])


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
        agent.bus = Mock()

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
        agent.bus = Mock()
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
        agent.bus = Mock()

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
        assert agent.bus.publish.called
        assert agent.entities_emitted == 1

    @patch("orpheus_agent_event_correlator.main.OrpheusConfig")
    def test_shutdown_persists_open_cluster_not_just_publishes(
        self,
        mock_orpheus_config_class: Mock,
        tmp_path: Any,
    ) -> None:
        """shutdown() must route flush_all output through _on_entity_ready
        so the open cluster reaches SQLite — not just MQTT.

        Regression: previously shutdown iterated flush_all() and called
        _publish_entity directly, skipping _persist_entity. Open clusters
        at SIGTERM were broadcast over MQTT but lost from the Entity DB
        across restarts."""

        mock_orpheus_config_class.get_instance.return_value = Mock(
            mqtt=Mock(broker_host="localhost", broker_port=1883)
        )

        agent = EventCorrelatorAgent(window_seconds=3.0)
        agent.db = DetectionDB(db_path=tmp_path / "test.db")
        agent.bus = Mock()
        # Constructor doesn't auto-create cluster_manager (that's done
        # in ``start()`` once the event loop is up); wire it explicitly
        # the way the other tests in this file do.
        agent.cluster_manager = ClusterManager(
            window_seconds=3.0,
            on_entity_ready=agent._on_entity_ready,
        )

        # Seed an open cluster the way an MQTT detection event would.
        bird_detection = Detection(
            event_id="bird-det-shutdown-001",
            event_timestamp=datetime.now(timezone.utc),
            timestamp=datetime.now(timezone.utc),
            detection_type="species.detected",
            channel=1,
            species_code="amecro",
            species_common="American Crow",
            confidence=0.91,
            audio_clip_path="/data/orpheus/audio/clip.flac",
            source_event_id="audio-motion-shutdown-001",
            context=SpatiotemporalContext(
                lat=40.7128,
                lon=-74.0060,
                sensor_id="mic-1",
            ),
        )
        agent._on_detection_event(
            "orpheus/detection/bird/events",
            bird_detection.model_dump(mode="json"),
        )

        # Sanity: cluster is open before shutdown.
        assert agent.cluster_manager is not None
        assert agent.cluster_manager._open_cluster is not None

        # Drive shutdown.
        asyncio.run(agent.shutdown())

        # The open cluster must have BOTH:
        #   1. Been published over MQTT (existing contract).
        #   2. Been persisted to SQLite (the regression we're guarding).
        assert agent.bus.publish.called
        entities = agent.db.get_entities()
        assert len(entities) == 1
        assert entities[0].species == "amecro"
        # No open cluster left after shutdown.
        assert agent.cluster_manager._open_cluster is None


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
        agent.bus = Mock()
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
    async def test_max_duration_cap_force_closes_cluster(self) -> None:
        """Under continuous-noise conditions (observations arriving faster
        than window_seconds), the timer would naively be rescheduled
        forever. The max_cluster_duration_seconds cap forces the cluster
        to close, even when observations keep arriving."""
        emitted_events: list[dict[str, Any]] = []

        def capture_entity(event: dict[str, Any]) -> None:
            emitted_events.append(event)

        loop = asyncio.get_running_loop()
        # window=0.2s, max_duration=0.4s. We'll feed observations every
        # 0.1s (< window) for 0.6s; without the cap, the cluster would
        # never expire. With the cap, it must close at ~0.4s.
        manager = ClusterManager(
            window_seconds=0.2,
            max_cluster_duration_seconds=0.4,
            on_entity_ready=capture_entity,
        )
        manager.set_loop(loop)

        for i in range(6):
            obs = Observation(
                species_code="amecro",
                common_name="American Crow",
                confidence=0.5 + i * 0.05,
                event_id=f"evt-{i}",
                source_event_id=f"src-{i}",
                sensor_id="mic-1",
                clip_path=f"/data/clip{i}.flac",
                context=None,
            )
            manager.process_observation(obs)
            await asyncio.sleep(0.1)

        # After ~0.6s of steady arrivals, the cap should have force-closed
        # the cluster at least once. Without the cap, emitted_events would
        # still be empty.
        await asyncio.sleep(0.5)
        assert len(emitted_events) >= 1, (
            "max_cluster_duration_seconds cap did not force-close the cluster "
            "under continuous-noise conditions"
        )

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
        agent.bus = Mock()

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

        # Source-identity: robin and sparrow are different sources → two
        # Entities, each unpacked from the legacy root-level payload.
        assert len(emitted_events) == 2
        assert {e["species_code"] for e in emitted_events} == {"amerob", "houspa"}

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
        agent.bus = Mock()
        agent.cluster_manager = ClusterManager(window_seconds=3.0)

        # Payload missing required 'timestamp' and 'detection_type'
        bad_payload: dict[str, Any] = {"event_id": "bad-event", "random_field": 42}

        agent._on_detection_event("orpheus/detection/bird/events", bad_payload)

        assert agent.events_ignored == 1
        assert len(agent.cluster_manager._clusters) == 0


class TestEntityTypeEmission:
    """The correlator derives + emits entity_type on EntityEvents ([ARCH])."""

    def _emit(self, observation: Observation) -> list[dict[str, Any]]:
        mgr = ClusterManager(window_seconds=3.0)
        mgr.process_observation(observation)
        return mgr.flush_all()

    def test_corvid_emits_crow(self) -> None:
        events = self._emit(
            Observation(
                species_code="corvus", common_name="American Crow", confidence=0.9,
                event_id="d1", source_event_id="r1", sensor_id="mic-1", clip_path=None,
                context=None,
                taxonomy={"namespace": "ioc", "id": "Corvus brachyrhynchos"},
                detection_type="species.detected",
            )
        )
        assert len(events) == 1
        assert events[0]["entity_type"] == "Animal.Bird.Crow"
        # entity_type is consistent with the display species_code.
        assert events[0]["species_code"] == "corvus"

    def test_generic_bird_coarsens_to_animal_bird(self) -> None:
        events = self._emit(
            Observation(
                species_code="amerob", common_name="American Robin", confidence=0.9,
                event_id="d1", source_event_id="r1", sensor_id="mic-1", clip_path=None,
                context=None,
                taxonomy={"namespace": "ioc", "id": "Turdus migratorius"},
                detection_type="species.detected",
            )
        )
        assert events[0]["entity_type"] == "Animal.Bird"

    def test_unresolvable_is_none(self) -> None:
        events = self._emit(
            Observation(
                species_code="unknownx", common_name="Unknown", confidence=0.5,
                event_id="d1", source_event_id="r1", sensor_id="mic-1", clip_path=None,
                context=None, taxonomy=None, detection_type="audio.classified",
            )
        )
        assert events[0]["entity_type"] is None


class TestExpiryFailureAccounting:
    """The expiry path runs as a bare timer callback: a failure must be
    counted and survivable, never a silent cluster loss."""

    def _obs(self, event_id: str, **kw) -> Observation:
        return Observation(
            species_code="amecro",
            common_name="American Crow",
            confidence=0.9,
            event_id=event_id,
            source_event_id=f"src-{event_id}",
            sensor_id="mic-1",
            clip_path="/data/clip.flac",
            context=None,
            **kw,
        )

    @pytest.mark.asyncio
    async def test_expiry_failure_is_counted_not_swallowed(self) -> None:
        def boom(event: dict[str, Any]) -> None:  # noqa: ARG001 — emit hook signature
            raise RuntimeError("emit exploded")

        manager = ClusterManager(window_seconds=0.1, on_entity_ready=boom)
        manager.set_loop(asyncio.get_running_loop())
        manager.process_observation(self._obs("evt-1"))
        await asyncio.sleep(0.25)

        assert manager.expire_errors == 1
        assert "emit exploded" in (manager.last_expire_error or "")

        # The manager keeps working after a failed expiry.
        captured: list[dict[str, Any]] = []
        manager.on_entity_ready = captured.append
        manager.process_observation(self._obs("evt-2"))
        await asyncio.sleep(0.25)
        assert len(captured) == 1
        assert manager.expire_errors == 1

    def test_observation_naive_timestamp_normalized_to_utc(self) -> None:
        naive = datetime(2026, 8, 22, 10, 0, 0)  # noqa: DTZ001 — naive on purpose
        obs = self._obs("evt-naive", timestamp=naive)
        assert obs.timestamp.tzinfo is not None
        assert obs.timestamp == naive.replace(tzinfo=timezone.utc)
