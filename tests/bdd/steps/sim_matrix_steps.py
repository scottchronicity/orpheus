"""Step definitions for the Simulacrum test matrix — agent-failure (n-k down).

Drives the real event-correlator (set up in ``environment.py``) with the
*surviving* classifiers' synthetic detections and asserts the whole-system DB
output: one fused entity whose evidence types are exactly the surviving
classifiers' output types. The "down" agent is simply one whose detection is never
injected. See docs/designs/sim-test-matrix.md.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from behave import given, then, when
from orpheus_common.detection import is_corvid_species_code

# The cascade classifiers and the contract each fulfils — one source of truth.
# type -> (input topic, output detection_type).
CONTRACT = {
    "bird-detection": ("orpheus/detection/bird/events", "species.detected"),
    "crow-detection": ("orpheus/detection/crow/events", "crow.analyzed"),
    "audio-events": ("orpheus/detection/audio/events", "audio.classified"),
}
CASCADE_CLASSIFIERS = list(CONTRACT)

# A corvid signal from each classifier about ONE physical event (shared root), with
# the taxonomy each really emits — bird=ioc, audio-events=audioset (cross-taxonomy),
# crow.analyzed carries none — so cross-classifier fusion is genuinely exercised.
_TAXONOMY: dict[str, dict | None] = {
    "bird-detection": {"namespace": "ioc", "id": "Corvus brachyrhynchos"},
    "crow-detection": None,
    "audio-events": {"namespace": "audioset", "id": "/m/04s8yn", "common_name": "Crow"},
}
_ROOT = "root-matrix"


def _synth(clf: str) -> dict:
    """A contract-shaped detection for ``clf`` — corvid, same root + overlapping
    time so the survivors fuse into one entity."""
    _topic, detection_type = CONTRACT[clf]
    return {
        "event_id": f"det-{clf}-{uuid.uuid4().hex[:8]}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "detection_type": detection_type,
        "species_code": "corvus",
        "species_common": "American Crow",
        "taxonomy": _TAXONOMY[clf],
        "context": {"sensor_id": "mic-1", "lat": 47.6, "lon": -122.3},
        "root_event_id": _ROOT,
        "source_event_id": _ROOT,
        "confidence": 0.9,
    }


def _csv(value: str) -> set[str]:
    return {p.strip() for p in value.split(",") if p.strip()}


@given("the surviving classifiers are everything except {down}")
def step_surviving(context, down: str) -> None:
    # down="none" -> all classifiers survive.
    context.surviving = [c for c in CASCADE_CLASSIFIERS if c != down]


@when("the surviving classifiers each report on one signal")
def step_report(context) -> None:
    for clf in context.surviving:
        topic, _dtype = CONTRACT[clf]
        context.agent._on_detection_event(topic, _synth(clf))
    # Force-expire the cluster and run each built entity through the real
    # on_entity_ready (tag + persist + publish) — what the expiry timer does.
    for entity_event in context.agent.cluster_manager.flush_all():
        context.agent._on_entity_ready(entity_event)
    context.entities = context.agent.db.get_entities()


@then("the DB has exactly 1 entity")
def step_one_entity(context) -> None:
    assert len(context.entities) == 1, [e.species for e in context.entities]
    context.entity = context.entities[0]


@then("the entity evidence types are exactly {types}")
def step_evidence_types(context, types: str) -> None:
    got = {ev.detection_type for ev in context.entity.evidence}
    assert got == _csv(types), f"got {got}, expected {_csv(types)}"


@then("the entity has at least 1 corvid evidence type")
def step_corvid(context) -> None:
    codes = [ev.species_code for ev in context.entity.evidence]
    assert any(is_corvid_species_code(c) for c in codes), codes


# --- multiplicity (D3): N instances of a type on distinct sensors fuse to one ---


def _synth_sensor(sensor_id: str) -> dict:
    """A corvid detection from one instance/mic. Distinct chain root per sensor
    (separate clips per mic) — fusion is via same_source (corvid), not a shared
    root, exactly the multi-instance case."""
    return {
        "event_id": f"det-{sensor_id}-{uuid.uuid4().hex[:8]}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "detection_type": "species.detected",
        "species_code": "corvus",
        "species_common": "American Crow",
        "taxonomy": {"namespace": "ioc", "id": "Corvus brachyrhynchos"},
        "context": {"sensor_id": sensor_id, "lat": 47.6, "lon": -122.3},
        "root_event_id": "root-" + sensor_id,
        "source_event_id": "root-" + sensor_id,
        "confidence": 0.9,
    }


@given("{count:d} instances of the same type observe one signal")
def step_instances(context, count: int) -> None:
    context.instance_dets = [_synth_sensor(f"mic-{i}") for i in range(count)]
    context.instance_count = count


@when("the correlator processes all instance detections")
def step_process_instances(context) -> None:
    for det in context.instance_dets:
        context.agent._on_detection_event("orpheus/detection/bird/events", det)
    for entity_event in context.agent.cluster_manager.flush_all():
        context.agent._on_entity_ready(entity_event)
    context.entities = context.agent.db.get_entities()


@then("the DB has 1 entity fused from {count:d} sensors")
def step_fused_sensors(context, count: int) -> None:
    assert len(context.entities) == 1, [e.species for e in context.entities]
    sig = context.entities[0].event_signature or {}
    sensors = set(sig.get("sensor_ids", []))
    assert len(sensors) == count, f"expected {count} sensors, got {sorted(sensors)}"


# --- the fuser is necessary: correlator-down + all-down canary (Slice 2) -------
# The generated powerset downs classifiers with the correlator always present;
# these pin the complementary corners — no fuser ⇒ no entities (even with full
# classifier signal), and no signal ⇒ no entities (even with the fuser up).


@given("the correlator is down")
def step_correlator_down(context) -> None:
    # "Down" = the fuser never consumes. Detections are published onto the bus but
    # no correlator runs _on_detection_event on them.
    context.emitted = []


@when("all classifiers report on one signal onto the bus")
def step_classifiers_emit_to_bus(context) -> None:
    for clf in CASCADE_CLASSIFIERS:
        topic, _dtype = CONTRACT[clf]
        det = _synth(clf)
        # Publish onto the bus, NOT into the correlator — the Mock bus captures the
        # publish but (correlator down) nothing dispatches it to a subscriber.
        context.agent.bus.publish(topic, det)
        context.emitted.append(det)
    context.entities = context.agent.db.get_entities()


@then("{count:d} classifier detections were emitted")
def step_n_emitted(context, count: int) -> None:
    assert len(context.emitted) == count, len(context.emitted)


@then("the DB has 0 entities")
def step_zero_entities(context) -> None:
    assert len(context.entities) == 0, [e.species for e in context.entities]


@given("the correlator is up with no classifiers reporting")
def step_correlator_up_idle(context) -> None:
    # context.agent IS the real correlator (environment.py); it is simply fed no
    # detections.
    pass


@when("the correlator processes its empty backlog")
def step_process_empty(context) -> None:
    for entity_event in context.agent.cluster_manager.flush_all():
        context.agent._on_entity_ready(entity_event)
    context.entities = context.agent.db.get_entities()


# --- topology (D2): all-on-one-host vs all-on-different-hosts fuse the same -----
# Host placement is a deploy concern the bus abstracts; it must not fragment the
# fused entity. Sensor is held constant (one signal) so only the host varies.

_HOSTS_BY_TOPOLOGY: dict[str, dict[str, str]] = {
    "one host": dict.fromkeys(CASCADE_CLASSIFIERS, "jetson-1"),
    "different hosts": {
        "bird-detection": "jetson-1",
        "crow-detection": "nuc-1",
        "audio-events": "pi-1",
    },
}


@when("the full cascade reports one signal with agents on {topology}")
def step_cascade_topology(context, topology: str) -> None:
    hosts = _HOSTS_BY_TOPOLOGY[topology]
    for clf in CASCADE_CLASSIFIERS:
        det = _synth(clf)
        # Same signal (shared root + sensor); only the host placement varies.
        det["context"] = {**det["context"], "host": hosts[clf]}
        context.agent._on_detection_event(CONTRACT[clf][0], det)
    for entity_event in context.agent.cluster_manager.flush_all():
        context.agent._on_entity_ready(entity_event)
    context.entities = context.agent.db.get_entities()
