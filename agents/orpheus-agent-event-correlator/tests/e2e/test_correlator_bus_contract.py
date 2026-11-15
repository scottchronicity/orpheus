"""Event-correlator bus-behavior oracle (e2e, real NATS) — the CONSUMER side.

The crow oracle pins what crow PUBLISHES; this pins what the correlator CONSUMES
and emits, so a detection-contract drift breaks a test on whichever end moved —
WHEN the suite runs. It is currently MANUAL-ONLY: no CI job provisions a
nats-server or invokes `make test-e2e` (the unit gate excludes `-m e2e`), and
without a broker every test skips. Run locally via `make sim-up` +
`make test-e2e` until CI wires in a broker.

Runs the real EventCorrelatorAgent (no stubs) against a real broker and asserts
only on the EntityEvent it publishes. Skips when no broker is reachable.
"""

from __future__ import annotations

import asyncio
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from orpheus_agent_audio_playback.main import AudioPlaybackAgent
from orpheus_common import create_event_bus
from orpheus_common.config import OrpheusConfig
from orpheus_common.detection import Detection
from orpheus_common.detection.models import TaxonomyRef
from orpheus_common.testing import AgentRunner, Observer, publish

pytestmark = pytest.mark.e2e


def _wait_until(pred, timeout: float = 6.0, interval: float = 0.02) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(interval)
    return pred()


ENTITY_TOPIC = "orpheus/entities/animal"
BIRD_TOPIC = "orpheus/detection/bird/events"
CROW_TOPIC = "orpheus/detection/crow/events"
HEALTH_TOPIC = "orpheus/system/event-correlator/health"

_CORVID_TAX = TaxonomyRef(namespace="ioc", id="Corvus brachyrhynchos", common_name="American Crow")


def _species_detected(
    root: str,
    event_id: str,
    sensor: str = "mic-1",
    *,
    species_code: str = "amecro",
    species_common: str = "American Crow",
    timestamp: datetime | None = None,
) -> dict:
    """A BirdNET-shaped species.detected for a corvid (sim-source shape)."""
    taxonomy = (
        _CORVID_TAX
        if species_code == "amecro"
        else TaxonomyRef(namespace="ioc", id=species_code, common_name=species_common)
    )
    return Detection(
        event_id=event_id,
        timestamp=timestamp or datetime.now(UTC),
        detection_type="species.detected",
        species_code=species_code,
        species_common=species_common,
        confidence=0.9,
        root_event_id=root,
        source_event_id=event_id,
        context={"sensor_id": sensor, "lat": 47.6, "lon": -122.3},
        taxonomy=taxonomy,
    ).model_dump(mode="json")


class _ControlledPlayer:
    """A non-audible player double that holds playback open for bus assertions."""

    def __init__(self, *, failure: Exception | None = None, start_failure: Exception | None = None):
        self.entered_wait = threading.Event()
        self.release = threading.Event()
        self.failure = failure
        self.start_failure = start_failure

    async def play(self, *_args, **_kwargs):
        if self.start_failure:
            raise self.start_failure

    async def wait(self):
        self.entered_wait.set()
        await asyncio.to_thread(self.release.wait, 5.0)
        if self.failure:
            raise self.failure
        return True


def _playback_thread(agent, player, label: str):
    errors = []

    def run():
        try:
            asyncio.run(
                agent._play_sound_async(player, Path("controlled-test.wav"), 1, 0.0, label)
            )
        except Exception as exc:  # surfaced to the test thread
            errors.append(exc)

    thread = threading.Thread(target=run, name="e2e-audio-playback", daemon=True)
    thread.start()
    return thread, errors


def _wait_for_playback_window(agent, event: dict) -> bool:
    point = {
        "event_signature": {
            "start_time": event["start_time"],
            "end_time": event["start_time"],
        }
    }
    return _wait_until(lambda: agent.corollary_discharge.is_self_generated(point), timeout=3.0)


def _audio_agent(nats_url: str) -> AudioPlaybackAgent:
    config = OrpheusConfig.from_dict(
        {"event_bus": {"backend": "nats", "nats_url": nats_url}}, source="<e2e>"
    )
    agent = AudioPlaybackAgent()
    agent._config = config
    agent._mqtt_client = create_event_bus(config, client_id=f"e2e-playback-{time.time_ns()}")
    agent._mqtt_client.connect()
    return agent


def _crow_analyzed(root: str, event_id: str, sensor: str = "mic-1") -> dict:
    """The exact crow.analyzed shape the crow agent emits (taxonomy deliberately
    None — crow is a call-type analyzer, not a species claim)."""
    return Detection(
        event_id=event_id,
        timestamp=datetime.now(UTC),
        detection_type="crow.analyzed",
        species_code="american_crow",
        species_common="Crow",
        confidence=0.92,
        root_event_id=root,
        source_event_id=event_id,
        context={"sensor_id": sensor},
        taxonomy=None,
        metadata={"call_type": "caw", "confirmed_crow": True},
    ).model_dump(mode="json")


def test_species_burst_produces_one_entity(correlator, nats_url):
    """CO1+CO2+CO4: two same-root species.detected fuse into ONE EntityEvent on
    the entities topic, carrying evidence + species + a stable id."""
    root = "root-burst-1"
    with Observer(nats_url, ENTITY_TOPIC, client_id="corr-obs1") as obs, AgentRunner(correlator):
        publish(nats_url, BIRD_TOPIC, _species_detected(root, "det-1"))
        publish(nats_url, BIRD_TOPIC, _species_detected(root, "det-2"))
        assert obs.wait_for(1, timeout=6.0), "expected one EntityEvent"

    entities = obs.payloads_on(ENTITY_TOPIC)
    assert len(entities) == 1
    ent = entities[0]
    for key in ("entity_id", "species_code", "confidence", "evidence"):
        assert key in ent
    assert isinstance(ent["evidence"], list)
    assert len(ent["evidence"]) >= 1


def test_consumes_crow_analyzed_as_evidence(correlator, nats_url):
    """The OTHER SIDE of the crow contract: a crow.analyzed (crow's exact output
    shape) on the same root as a species.detected is consumed and merged into the
    entity's evidence — producer + consumer agree on the message shape."""
    root = "root-chain-1"
    with Observer(nats_url, ENTITY_TOPIC, client_id="corr-obs2") as obs, AgentRunner(correlator):
        publish(nats_url, BIRD_TOPIC, _species_detected(root, "bird-1"))
        publish(nats_url, CROW_TOPIC, _crow_analyzed(root, "crow-1"))
        assert obs.wait_for(1, timeout=6.0), "expected an EntityEvent fusing both"

    ent = obs.payloads_on(ENTITY_TOPIC)[-1]
    source_ids = {ev.get("source_event_id") for ev in ent["evidence"]}
    assert "crow-1" in source_ids, f"crow.analyzed not consumed as evidence: {source_ids}"


def test_audio_motion_is_ignored(correlator, nats_url):
    """CO5: a raw audio.motion trigger never becomes an entity; a real detection
    sent alongside still does (non-vacuous)."""
    motion = Detection(
        event_id="motion-1",
        timestamp=datetime.now(UTC),
        detection_type="audio.motion",
        confidence=0.5,
        root_event_id="root-motion",
    ).model_dump(mode="json")
    with Observer(nats_url, ENTITY_TOPIC, client_id="corr-obs3") as obs, AgentRunner(correlator):
        publish(nats_url, BIRD_TOPIC, motion)
        publish(nats_url, BIRD_TOPIC, _species_detected("root-real", "real-1"))
        assert obs.wait_for(1, timeout=6.0)

    entities = obs.payloads_on(ENTITY_TOPIC)
    assert len(entities) == 1  # only the species.detected became an entity
    assert entities[0]["evidence"][0]["source_event_id"] != "motion-1"


def test_startup_health_online(correlator, nats_url):
    """C3: the correlator announces itself online on its health topic at startup."""
    with Observer(nats_url, HEALTH_TOPIC, client_id="corr-health") as obs, AgentRunner(correlator):
        assert obs.wait_for(1, timeout=8.0), "expected a startup health message"
        startup = obs.payloads_on(HEALTH_TOPIC)[0]
        assert startup["status"] == "online"


def test_shutdown_flushes_open_cluster(correlator_no_expiry, nats_url):
    """CO6: an open cluster (window not yet expired) is STILL emitted when the
    correlator shuts down — the flush publishes BEFORE disconnect, so the most
    recent cluster isn't lost across a restart. The window is long here, so only
    the shutdown flush (not the expiry timer) can produce the entity. This guards
    the shutdown ordering an Actor-base conversion must preserve (flush while the
    bus is still connected)."""
    with Observer(nats_url, ENTITY_TOPIC, client_id="corr-flush") as obs:
        with AgentRunner(correlator_no_expiry):
            publish(nats_url, BIRD_TOPIC, _species_detected("root-flush", "flush-1"))
            # Detection is received + clustered, but the 30s window won't expire.
            assert _wait_until(lambda: correlator_no_expiry.events_received >= 1), "not received"
            assert obs.payloads_on(ENTITY_TOPIC) == []  # no expiry yet → entity only via flush
        # AgentRunner exit -> shutdown -> flush_all -> the open cluster is published.
        assert obs.wait_for(1, timeout=6.0), "open cluster was not flushed on shutdown"

    entities = obs.payloads_on(ENTITY_TOPIC)
    assert len(entities) == 1
    assert entities[0].get("evidence"), "flushed entity carries no evidence"


def test_real_playback_events_tag_persisted_overlap_and_keep_unrelated_wildlife(
    correlator_with_corollary, nats_url
):
    """Playback publisher, NATS subscription, correlation and SQLite use real code.

    Only the player is controlled: no speaker output is produced during an e2e
    run. A wildlife detection during playback remains published, persisted, and
    present as entity evidence even though it receives the self-generated tag.
    """
    corr = correlator_with_corollary
    with (
        Observer(
            nats_url,
            ENTITY_TOPIC,
            AudioPlaybackAgent.TOPIC_ACTUATION_AUDIO_PLAYBACK,
            client_id="playback-corollary-e2e",
        ) as obs,
        AgentRunner(corr),
    ):
        playback = _audio_agent(nats_url)
        player = _ControlledPlayer()
        thread, errors = _playback_thread(playback, player, "crow-call-test")
        try:
            assert player.entered_wait.wait(3.0)
            assert obs.wait_for_match(
                lambda payload: payload.get("phase") == "started", timeout=3.0
            )
            started = next(
                event
                for event in obs.payloads_on(AudioPlaybackAgent.TOPIC_ACTUATION_AUDIO_PLAYBACK)
                if event.get("phase") == "started"
            )
            assert started["source"] == "audio_playback_agent"
            assert started["sound_name"] == "crow-call-test"
            assert started["duration_seconds"] == 0.0
            assert _wait_for_playback_window(corr, started), "correlator missed started event"

            overlap_id = "e2e-overlap-crow"
            publish(nats_url, BIRD_TOPIC, _species_detected("root-e2e-overlap", overlap_id))
            assert _wait_until(lambda: corr.events_received >= 1), "correlator missed detection"
            time.sleep(0.1)
            player.release.set()
            thread.join(timeout=5.0)
            assert not thread.is_alive(), "playback did not finish"
            assert errors == []

            assert obs.wait_for_match(
                lambda payload: payload.get("phase") == "finished", timeout=3.0
            )
            events = obs.payloads_on(AudioPlaybackAgent.TOPIC_ACTUATION_AUDIO_PLAYBACK)
            started, finished = next(e for e in events if e["phase"] == "started"), next(
                e for e in events if e["phase"] == "finished"
            )
            assert started["playback_id"] == finished["playback_id"]
            assert started["start_time"] == finished["start_time"]
            assert finished["duration_seconds"] >= 0.05
            assert finished["playback_status"] == "completed"

            assert _wait_until(
                lambda: any(
                    overlap_id in {e.get("source_event_id") for e in payload.get("evidence", [])}
                    for payload in obs.payloads_on(ENTITY_TOPIC)
                ),
                timeout=5.0,
            ), "overlapping wildlife detection was not published as an entity"
            overlapping = next(
                entity
                for entity in obs.payloads_on(ENTITY_TOPIC)
                if overlap_id
                in {e.get("source_event_id") for e in entity.get("evidence", [])}
            )
            assert overlapping["is_self_generated"] is True
            persisted_overlap = corr.db.get_entity_by_id(overlapping["entity_id"])
            assert persisted_overlap is not None
            assert persisted_overlap.is_self_generated is True

            # The later Robin is outside the measured playback window and must
            # remain a normal, published, persisted wildlife observation.
            unrelated_id = "e2e-unrelated-robin"
            later = datetime.now(UTC) + timedelta(seconds=finished["duration_seconds"] + 2.0)
            publish(
                nats_url,
                BIRD_TOPIC,
                _species_detected(
                    "root-e2e-unrelated",
                    unrelated_id,
                    species_code="amerob",
                    species_common="American Robin",
                    timestamp=later,
                ),
            )
            assert _wait_until(
                lambda: any(
                    unrelated_id
                    in {e.get("source_event_id") for e in payload.get("evidence", [])}
                    for payload in obs.payloads_on(ENTITY_TOPIC)
                ),
                timeout=5.0,
            ), "unrelated wildlife detection was not published"
            unrelated = next(
                entity
                for entity in obs.payloads_on(ENTITY_TOPIC)
                if unrelated_id
                in {e.get("source_event_id") for e in entity.get("evidence", [])}
            )
            assert unrelated["is_self_generated"] is False
            persisted_unrelated = corr.db.get_entity_by_id(unrelated["entity_id"])
            assert persisted_unrelated is not None
            assert persisted_unrelated.is_self_generated is False
            assert overlap_id in {e.get("source_event_id") for e in overlapping["evidence"]}
        finally:
            player.release.set()
            thread.join(timeout=5.0)
            playback._mqtt_client.disconnect()


def test_real_bus_interrupted_playback_tags_and_backend_start_failure_has_no_window(
    correlator_with_corollary, nats_url
):
    corr = correlator_with_corollary
    with (
        Observer(
            nats_url,
            ENTITY_TOPIC,
            AudioPlaybackAgent.TOPIC_ACTUATION_AUDIO_PLAYBACK,
            AudioPlaybackAgent.TOPIC_RESPONSE,
            client_id="playback-failure-e2e",
        ) as obs,
        AgentRunner(corr),
    ):
        playback = _audio_agent(nats_url)
        try:
            failed_start = _ControlledPlayer(start_failure=RuntimeError("CoreAudio unavailable"))
            thread, errors = _playback_thread(playback, failed_start, "failed-start")
            thread.join(timeout=3.0)
            assert not thread.is_alive()
            assert errors == []  # the playback agent reports the failure itself
            assert obs.wait_for_match(
                lambda payload: payload.get("status") == "error", timeout=3.0
            )
            assert obs.payloads_on(AudioPlaybackAgent.TOPIC_ACTUATION_AUDIO_PLAYBACK) == []

            failed_id = "e2e-no-window"
            publish(
                nats_url,
                BIRD_TOPIC,
                _species_detected(
                    "root-no-window",
                    failed_id,
                    species_code="amerob",
                    species_common="American Robin",
                ),
            )
            assert _wait_until(lambda: corr.events_received >= 1)
            assert _wait_until(
                lambda: any(
                    failed_id in {e.get("source_event_id") for e in p.get("evidence", [])}
                    for p in obs.payloads_on(ENTITY_TOPIC)
                ),
                timeout=5.0,
            )
            no_window_entity = next(
                p
                for p in obs.payloads_on(ENTITY_TOPIC)
                if failed_id in {e.get("source_event_id") for e in p.get("evidence", [])}
            )
            assert no_window_entity["is_self_generated"] is False

            interrupted = _ControlledPlayer(failure=RuntimeError("output disconnected"))
            thread, errors = _playback_thread(playback, interrupted, "interrupted-call")
            assert interrupted.entered_wait.wait(3.0)
            assert obs.wait_for_match(
                lambda p: p.get("phase") == "started" and p.get("sound_name") == "interrupted-call",
                timeout=3.0,
            )
            start_event = next(
                p
                for p in obs.payloads_on(AudioPlaybackAgent.TOPIC_ACTUATION_AUDIO_PLAYBACK)
                if p.get("phase") == "started" and p.get("sound_name") == "interrupted-call"
            )
            assert _wait_for_playback_window(corr, start_event)
            interrupted_id = "e2e-interrupted-overlap"
            publish(nats_url, BIRD_TOPIC, _species_detected("root-interrupted", interrupted_id))
            assert _wait_until(lambda: corr.events_received >= 2)
            time.sleep(0.1)
            interrupted.release.set()
            thread.join(timeout=5.0)
            assert not thread.is_alive()
            assert errors == []
            assert obs.wait_for_match(
                lambda p: p.get("phase") == "finished"
                and p.get("playback_id") == start_event["playback_id"],
                timeout=3.0,
            )
            finished = next(
                p
                for p in obs.payloads_on(AudioPlaybackAgent.TOPIC_ACTUATION_AUDIO_PLAYBACK)
                if p.get("phase") == "finished"
                and p.get("playback_id") == start_event["playback_id"]
            )
            assert finished["playback_status"] == "interrupted"
            assert finished["duration_seconds"] >= 0.05
            assert obs.wait_for_match(
                lambda p: interrupted_id
                in {e.get("source_event_id") for e in p.get("evidence", [])},
                timeout=5.0,
            )
            tagged = next(
                p
                for p in obs.payloads_on(ENTITY_TOPIC)
                if interrupted_id in {e.get("source_event_id") for e in p.get("evidence", [])}
            )
            assert tagged["is_self_generated"] is True
        finally:
            playback._mqtt_client.disconnect()


def test_real_bus_playback_window_does_not_tag_when_corollary_is_disabled(correlator, nats_url):
    corr = correlator
    assert corr.health_payload("startup")["corollary_discharge_enabled"] is False
    with (
        Observer(
            nats_url,
            ENTITY_TOPIC,
            AudioPlaybackAgent.TOPIC_ACTUATION_AUDIO_PLAYBACK,
            client_id="playback-disabled-e2e",
        ) as obs,
        AgentRunner(corr),
    ):
        playback = _audio_agent(nats_url)
        player = _ControlledPlayer()
        thread, errors = _playback_thread(playback, player, "disabled-call")
        try:
            assert player.entered_wait.wait(3.0)
            assert obs.wait_for_match(
                lambda p: p.get("phase") == "started", timeout=3.0
            )
            started = next(
                p
                for p in obs.payloads_on(AudioPlaybackAgent.TOPIC_ACTUATION_AUDIO_PLAYBACK)
                if p.get("phase") == "started"
            )
            disabled_id = "e2e-disabled-overlap"
            publish(nats_url, BIRD_TOPIC, _species_detected("root-disabled", disabled_id))
            assert _wait_until(lambda: corr.events_received >= 1)
            player.release.set()
            thread.join(timeout=5.0)
            assert not thread.is_alive()
            assert errors == []
            assert obs.wait_for_match(
                lambda p: p.get("phase") == "finished"
                and p.get("playback_id") == started["playback_id"],
                timeout=3.0,
            )
            assert obs.wait_for_match(
                lambda p: disabled_id
                in {e.get("source_event_id") for e in p.get("evidence", [])},
                timeout=5.0,
            )
            entity = next(
                p
                for p in obs.payloads_on(ENTITY_TOPIC)
                if disabled_id in {e.get("source_event_id") for e in p.get("evidence", [])}
            )
            assert entity["is_self_generated"] is False
        finally:
            player.release.set()
            thread.join(timeout=5.0)
            playback._mqtt_client.disconnect()
