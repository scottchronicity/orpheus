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

import time
from datetime import datetime, timezone

import pytest
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


def _species_detected(root: str, event_id: str, sensor: str = "mic-1") -> dict:
    """A BirdNET-shaped species.detected for a corvid (sim-source shape)."""
    return Detection(
        event_id=event_id,
        timestamp=datetime.now(timezone.utc),
        detection_type="species.detected",
        species_code="amecro",
        species_common="American Crow",
        confidence=0.9,
        root_event_id=root,
        source_event_id=root,
        context={"sensor_id": sensor, "lat": 47.6, "lon": -122.3},
        taxonomy=_CORVID_TAX,
    ).model_dump(mode="json")


def _crow_analyzed(root: str, event_id: str, sensor: str = "mic-1") -> dict:
    """The exact crow.analyzed shape the crow agent emits (taxonomy deliberately
    None — crow is a call-type analyzer, not a species claim)."""
    return Detection(
        event_id=event_id,
        timestamp=datetime.now(timezone.utc),
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
        timestamp=datetime.now(timezone.utc),
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
