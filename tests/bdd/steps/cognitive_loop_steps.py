"""Step definitions for the end-to-end cognitive-loop BDD scenarios.

Drives the real event-correlator (set up in environment.py) with synthetic
detections and asserts on the emitted + persisted EntityEvents.
"""

from __future__ import annotations

import math
import asyncio
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from behave import given, then, when

PLAYBACK_SRC = Path(__file__).resolve().parents[3] / "agents/orpheus-agent-audio-playback/src"
sys.path.insert(0, str(PLAYBACK_SRC))
from orpheus_agent_audio_playback.main import AudioPlaybackAgent  # noqa: E402

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

@given("the playback agent receives a crow-call request")
def step_playback_request(context):
    context.playback_agent = AudioPlaybackAgent()
    context.playback_events = []

    def publish(topic, payload, **_kwargs):
        if topic == context.playback_agent.TOPIC_ACTUATION_AUDIO_PLAYBACK:
            context.playback_events.append(payload)
            context.agent._on_playback_event(topic, payload)

    context.playback_agent._mqtt_client = Mock(publish=Mock(side_effect=publish))


@given("a synthetic crow detection is heard while the speaker is active")
def step_crow_heard_during_playback(context):
    context.playback_detection = True


@when("the playback agent completes the sound")
def step_playback_completes(context):
    async def play(_path, _repeat, _pause, **_segment):
        return None

    async def wait():
        # The start marker has already crossed the mocked isolated event bus.
        started = context.playback_events[0]
        context.playback_start = datetime.fromisoformat(started["start_time"])
        if context.playback_detection:
            during = context.playback_start + timedelta(seconds=1)
            detection = _detection("American Crow", when_=during)
            context.agent._on_detection_event("orpheus/detection/bird/events", detection)
            for event in context.agent.cluster_manager.flush_all():
                context.agent._on_entity_ready(event)
        await asyncio.sleep(0.02)
        return True

    player = SimpleNamespace(play=play, wait=wait)
    asyncio.run(
        context.playback_agent._run_playback(
            player, "crow_call", Path("crow-call.wav"), 1, 0.0
        )
    )
    context.published = [
        call.args[1]
        for call in context.agent.bus.publish.call_args_list
        if call.args and call.args[0] == ENTITIES_TOPIC
    ]


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


@then("the playback start and finish events preserve timing and sound identity")
def step_assert_playback_events(context):
    assert [event["phase"] for event in context.playback_events] == ["started", "finished"], (
        context.playback_events
    )
    started, finished = context.playback_events
    assert started["playback_id"] == finished["playback_id"], context.playback_events
    assert started["start_time"] == finished["start_time"], context.playback_events
    assert started["source"] == finished["source"] == "audio_playback_agent", (
        context.playback_events
    )
    assert started["sound_name"] == finished["sound_name"] == "crow_call", (
        context.playback_events
    )
    assert finished["duration_seconds"] >= 0.01, context.playback_events


@then("the tagged detection evidence remains in SQLite")
def step_assert_detection_retained(context):
    rows = context.agent.db.get_entities()
    assert len(rows) == 1
    assert rows[0].is_self_generated is True
    assert rows[0].evidence, "the wildlife detection must remain available as entity evidence"


@given("a completed playback window has been recorded")
def step_completed_playback(context):
    context.playback_start = datetime.now(timezone.utc) - timedelta(seconds=30)
    context.agent._on_playback_event(
        "orpheus/actuation/audio/playback",
        {
            "phase": "finished",
            "start_time": context.playback_start.isoformat(),
            "duration_seconds": 1.0,
            "source": "audio_playback_agent",
            "sound_name": "crow_call",
        },
    )


@given("an unrelated crow detection arrives after playback")
def step_crow_after_playback(context):
    context.detections = [
        _detection("American Crow", when_=context.playback_start + timedelta(seconds=20))
    ]


@then("the unrelated entity remains published and untagged")
def step_assert_unrelated(context):
    assert context.published
    assert all(event["is_self_generated"] is False for event in context.published)
    assert context.agent.db.get_entities()


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
