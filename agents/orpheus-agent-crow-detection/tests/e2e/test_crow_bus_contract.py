"""Crow-detection bus-behavior oracle (e2e, real NATS).

Pins the OBSERVABLE bus contract the actor-model refactor must preserve. Runs the
real CrowDetectionAgent (models/DB stubbed) against a real broker and asserts on
published topics/payloads only — never internals. Must stay green before and after
the refactor. Skips when no broker is reachable.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import pytest
from orpheus_common.detection import Detection
from orpheus_common.detection.models import TaxonomyRef
from orpheus_common.testing import AgentRunner, Observer, publish

pytestmark = pytest.mark.e2e

CROW_TOPIC = "orpheus/detection/crow/events"
BIRD_TOPIC = "orpheus/detection/bird/events"
AUDIO_TOPIC = "orpheus/detection/audio/events"
HEALTH_TOPIC = "orpheus/system/crow-detection/health"


def _bird_event(event_id: str, clip_path: str, *, is_corvid: bool) -> dict:
    """A legacy bird-detection payload (corvid or not) referencing a clip."""
    species = "amecro" if is_corvid else "rewbla"
    return {
        "event_id": event_id,
        "audio_clip_path": clip_path,
        "channel": "1",
        "detections": [{"is_corvid": is_corvid, "species_code": species}],
    }


def _audio_corvid_event(event_id: str, clip_path: str) -> dict:
    """A V2 audio.classified Detection tagged with the AudioSet 'Crow' mid."""
    return Detection(
        event_id=event_id,
        timestamp=datetime.now(timezone.utc),
        detection_type="audio.classified",
        species_code="crow",
        confidence=0.8,
        audio_clip_path=clip_path,
        taxonomy=TaxonomyRef(namespace="audioset", id="/m/04s8yn", common_name="Crow"),
    ).model_dump(mode="json")


def _clip(tmp_path, name: str = "clip.wav") -> str:
    p = tmp_path / name
    p.write_bytes(b"stub")  # must exist (agent checks); content unused (sf.read stubbed)
    return str(p)


def _wait_until(pred, timeout: float = 8.0, interval: float = 0.02) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(interval)
    return pred()


def test_corvid_bird_event_publishes_crow_analyzed(make_crow_agent, nats_url, tmp_path):
    """CR1+CR2: subscribed to bird events; a confirmed corvid → one
    `crow.analyzed` Detection on the crow topic, chained to the source event."""
    agent = make_crow_agent(is_crow=True)
    with Observer(nats_url, CROW_TOPIC, client_id="e2e-crow-obs") as obs, AgentRunner(agent):
        publish(nats_url, BIRD_TOPIC, _bird_event("bird_evt_001", _clip(tmp_path), is_corvid=True))
        assert obs.wait_for(1, timeout=8.0), "expected a crow.analyzed publish"

    payloads = obs.payloads_on(CROW_TOPIC)
    assert len(payloads) == 1
    det = payloads[0]
    assert det["detection_type"] == "crow.analyzed"
    assert det["source_event_id"] == "bird_evt_001"


def test_non_corvid_bird_event_is_silent(make_crow_agent, nats_url, tmp_path):
    """CR3: a non-corvid bird detection is processed but produces NO crow publish.
    Non-vacuous: a corvid event sent right after yields exactly one publish."""
    agent = make_crow_agent(is_crow=True)
    miss = _bird_event("noncorvid", _clip(tmp_path, "a.wav"), is_corvid=False)
    hit = _bird_event("corvid", _clip(tmp_path, "b.wav"), is_corvid=True)
    with Observer(nats_url, CROW_TOPIC, client_id="e2e-crow-obs2") as obs, AgentRunner(agent):
        publish(nats_url, BIRD_TOPIC, miss)
        publish(nats_url, BIRD_TOPIC, hit)
        assert obs.wait_for(1, timeout=8.0), "expected the corvid event to publish"
        # Both events were received by the agent (ordered dispatch).
        assert _wait_until(lambda: agent.events_processed >= 2)

    payloads = obs.payloads_on(CROW_TOPIC)
    assert len(payloads) == 1  # only the corvid produced output
    assert payloads[0]["source_event_id"] == "corvid"


def test_audio_events_corvid_signal_publishes_crow_analyzed(make_crow_agent, nats_url, tmp_path):
    """CR1 (2nd subscription): a corvid AudioSet tag on the audio-events topic
    also drives crow analysis — cross-classifier identity."""
    agent = make_crow_agent(is_crow=True)
    with Observer(nats_url, CROW_TOPIC, client_id="e2e-crow-obs3") as obs, AgentRunner(agent):
        publish(nats_url, AUDIO_TOPIC, _audio_corvid_event("audio_evt_001", _clip(tmp_path)))
        assert obs.wait_for(1, timeout=8.0), "expected crow.analyzed from the audio path"

    payloads = obs.payloads_on(CROW_TOPIC)
    assert len(payloads) == 1
    assert payloads[0]["detection_type"] == "crow.analyzed"
    assert payloads[0]["source_event_id"] == "audio_evt_001"


def test_health_lifecycle_online_then_offline(make_crow_agent, nats_url):
    """C3+C5+CR5: startup health is `online` with `models_loaded`; graceful
    shutdown publishes `offline` carrying the run stats."""
    agent = make_crow_agent(is_crow=True)
    with Observer(nats_url, HEALTH_TOPIC, client_id="e2e-crow-health") as obs:
        with AgentRunner(agent):
            assert obs.wait_for(1, timeout=8.0), "expected a startup health message"
            startup = obs.payloads_on(HEALTH_TOPIC)[0]
            assert startup["status"] == "online"
            assert "models_loaded" in startup  # crow-specific key (plural)
        # AgentRunner exit → graceful shutdown publishes the offline health.
        assert obs.wait_for(2, timeout=8.0), "expected an offline health on shutdown"

    offline = obs.payloads_on(HEALTH_TOPIC)[-1]
    assert offline["status"] == "offline"
    assert "events_processed" in offline
    assert "detections_found" in offline


def test_dedup_same_clip_emits_once(make_crow_agent, nats_url, tmp_path):
    """CR4: two corvid events on the SAME clip within the dedup window →
    only one crow.analyzed (AVES isn't run twice on the same clip)."""
    agent = make_crow_agent(is_crow=True)
    clip = _clip(tmp_path)
    with Observer(nats_url, CROW_TOPIC, client_id="e2e-crow-obs4") as obs, AgentRunner(agent):
        publish(nats_url, BIRD_TOPIC, _bird_event("dup1", clip, is_corvid=True))
        publish(nats_url, BIRD_TOPIC, _bird_event("dup2", clip, is_corvid=True))
        assert obs.wait_for(1, timeout=8.0)
        assert _wait_until(lambda: agent.events_processed >= 2)  # both received

    assert len(obs.payloads_on(CROW_TOPIC)) == 1  # second was deduped
