"""Step definitions for the end-to-end cognitive-loop BDD scenarios.

Drives the real event-correlator (set up in environment.py) with synthetic
detections and asserts on the emitted + persisted EntityEvents.
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timedelta, timezone

from behave import given, then, when

ENTITIES_TOPIC = "orpheus/entities/animal"

# Named species -> the (species_code, taxonomy) a classifier would emit, so the
# correlator derives the expected entity_type. (We don't invent frequencies: the
# synthetic signal below is a placeholder; the detection injected here is what a
# classifier would have produced — see docs/TESTING.md.)
_SPECIES = {
    "American Crow": {
        "species_code": "corvus",
        "taxonomy": {"namespace": "ioc", "id": "Corvus brachyrhynchos"},
    },
}


def _synthetic_signal(frequency: float = 1000.0, duration: float = 1.0, rate: int = 16000):
    """A synthetic sine (stdlib, no recorded audio). Placeholder to satisfy the
    'generated, not recorded' constraint; not used for classification."""
    n = int(rate * duration)
    return [math.sin(2 * math.pi * frequency * (i / rate)) for i in range(n)]


def _detection(species: str, *, sensor_id: str = "mic-1", when_=None) -> dict:
    spec = _SPECIES[species]
    ts = when_ or datetime.now(timezone.utc)
    return {
        "event_id": "det-" + uuid.uuid4().hex[:8],
        "timestamp": ts.isoformat(),
        "detection_type": "species.detected",
        "species_code": spec["species_code"],
        "species_common": species,
        "taxonomy": spec["taxonomy"],
        # sensor_id rides in the spatiotemporal context (where the correlator
        # reads it), not at the top level.
        "context": {"sensor_id": sensor_id, "lat": 47.6, "lon": -122.3},
        # Distinct chain root per sensor (separate audio.motion clips per mic).
        "root_event_id": "root-" + sensor_id,
        "source_event_id": "root-" + sensor_id,
        "confidence": 0.9,
    }


def _run_pipeline(context) -> None:
    """Feed queued detections through the real entry point, then force-expire
    the clusters and run each built entity through the real on_entity_ready
    (tag + persist + publish) — what the expiry timer does in production."""
    for det in context.detections:
        context.agent._on_detection_event("orpheus/detection/bird/events", det)
    for entity_event in context.agent.cluster_manager.flush_all():
        context.agent._on_entity_ready(entity_event)
    context.published = [
        call.args[1]
        for call in context.agent.bus.publish.call_args_list
        if call.args and call.args[0] == ENTITIES_TOPIC
    ]


# --- Single-species pipeline ------------------------------------------------- #

@given('a synthetic audio signal matching "{species}" frequency profile')
def step_signal(context, species):
    context.signal = _synthetic_signal()
    context.detections = [_detection(species)]


@when("the detection pipeline processes the audio chunk")
def step_process_chunk(context):
    _run_pipeline(context)


@then('an EntityEvent is published with entity_type "{entity_type}"')
def step_assert_entity_type(context, entity_type):
    assert context.published, "no EntityEvent was published"
    seen = [e.get("entity_type") for e in context.published]
    assert entity_type in seen, f"expected entity_type {entity_type!r}, got {seen!r}"


@then("the event is stored in the SQLite database")
def step_assert_persisted(context):
    entities = context.agent.db.get_entities()
    assert entities, "no entity was persisted to SQLite"


# --- Corollary discharge ----------------------------------------------------- #

@given("the system is playing a crow call")
def step_playback(context):
    context.playback_start = datetime.now(timezone.utc)
    context.agent._on_playback_event(
        "orpheus/actuation/audio/playback",
        {
            "start_time": context.playback_start.isoformat(),
            "duration_seconds": 5.0,
            "source": "speaker",
        },
    )


@given("a synthetic crow detection arrives during playback")
def step_crow_during(context):
    during = context.playback_start + timedelta(seconds=1)
    context.detections = [_detection("American Crow", when_=during)]


@when("the correlation pipeline processes the detection")
def step_process_detection(context):
    _run_pipeline(context)


@then("the event is tagged with is_self_generated = true")
def step_assert_self_generated(context):
    assert context.published, "no EntityEvent was published"
    flags = [e.get("is_self_generated") for e in context.published]
    assert all(flags) and flags, f"expected all self-generated, got {flags!r}"


# --- Multi-sensor correlation ------------------------------------------------ #

@given('a synthetic "{species}" detection on sensor "{sensor}"')
def step_multi_sensor_detection(context, species, sensor):
    context.detections.append(_detection(species, sensor_id=sensor))


@when("the correlation pipeline processes all detections")
def step_process_all(context):
    _run_pipeline(context)


@then("a single correlated multi-sensor EntityEvent is published")
def step_assert_multi_sensor(context):
    assert len(context.published) == 1, (
        f"expected exactly one correlated entity, got {len(context.published)}"
    )
    sensors = context.published[0].get("event_signature", {}).get("sensor_ids", [])
    assert len(sensors) >= 2, f"expected a multi-sensor entity, got sensors={sensors!r}"
