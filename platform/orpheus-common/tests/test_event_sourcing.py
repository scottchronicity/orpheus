"""Tests for the shared event-sourcing shadow helpers (ensure_domain_stream +
shadow_publish). Broker-free: a fake bus records the calls."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from orpheus_common import event_sourcing
from orpheus_common.event_sourcing import (
    DOMAIN_DETECTION_TOPICS,
    DOMAIN_SHADOW_PREFIX,
    domain_subject,
    ensure_domain_stream,
    shadow_publish,
)


class _FakeBus:
    def __init__(self, *, streams: bool = True) -> None:
        self.streams = streams
        self.ensured: list = []
        self.published: list = []
        self.publish_timeouts: list = []

    def stream_ensure(self, name, subjects, *, max_age=None, max_bytes=None, discard=None):
        if not self.streams:
            raise NotImplementedError("streams require a JetStream backend")
        self.ensured.append((name, list(subjects), max_age, max_bytes, discard))

    def stream_publish(self, subject, payload, *, msg_id=None, timeout=None):
        if not self.streams:
            raise NotImplementedError
        self.published.append((subject, payload, msg_id))
        self.publish_timeouts.append(timeout)


def _cfg(enabled):
    return SimpleNamespace(
        event_sourcing=SimpleNamespace(
            shadow_publish_enabled=enabled,
            stream_name="orpheus_domain",
            max_age_seconds=3600.0,
            max_bytes=1000,
        )
    )


class TestEnsureDomainStream:
    def test_off_by_default(self):
        bus = _FakeBus()
        assert ensure_domain_stream(bus, _cfg(False)) is False
        assert bus.ensured == []

    def test_enabled_ensures_all_domain_topics_with_retention(self):
        bus = _FakeBus()
        assert ensure_domain_stream(bus, _cfg(True)) is True
        assert len(bus.ensured) == 1
        name, subjects, max_age, max_bytes, discard = bus.ensured[0]
        assert name == "orpheus_domain"
        # The stream binds the PREFIXED shadow subjects, never the live topics —
        # a JetStream publish is a core publish, so binding the live subjects
        # would double-deliver every detection to every live subscriber.
        assert set(subjects) == {domain_subject(t) for t in DOMAIN_DETECTION_TOPICS}
        assert not set(subjects) & set(DOMAIN_DETECTION_TOPICS)
        assert max_age == 3600.0 and max_bytes == 1000 and discard == "old"

    def test_mqtt_backend_no_op(self):
        bus = _FakeBus(streams=False)  # stream_ensure raises NotImplementedError
        assert ensure_domain_stream(bus, _cfg(True)) is False

    def test_none_bus_is_off(self):
        assert ensure_domain_stream(None, _cfg(True)) is False


class TestShadowPublish:
    def test_publishes_keyed_by_event_id(self):
        bus = _FakeBus()
        det = SimpleNamespace(
            event_id="evt-1", model_dump=lambda mode=None: {"event_id": "evt-1", "x": 1}
        )
        shadow_publish(bus, "orpheus/detection/bird/events", det)
        # Callers pass the LIVE topic; the write lands on the shadow subject.
        assert bus.published == [
            ("orpheus/domain/detection/bird/events", {"event_id": "evt-1", "x": 1}, "evt-1")
        ]

    def test_never_publishes_on_a_live_topic(self):
        # The double-delivery guard: with the shadow flag on, live subscribers
        # (correlator, audio-events re-inference) must never see the shadow copy.
        bus = _FakeBus()
        det = SimpleNamespace(event_id="e", model_dump=lambda mode=None: {})
        for topic in DOMAIN_DETECTION_TOPICS:
            shadow_publish(bus, topic, det)
        assert len(bus.published) == len(DOMAIN_DETECTION_TOPICS)
        for subject, _, _ in bus.published:
            assert subject not in DOMAIN_DETECTION_TOPICS
            assert subject.startswith(DOMAIN_SHADOW_PREFIX + "/")

    def test_publishes_with_short_ack_budget(self):
        # The shadow rides the detection hot path: a broker brownout must cost
        # at most the short explicit budget, not the bus's 5s op default.
        bus = _FakeBus()
        det = SimpleNamespace(event_id="e", model_dump=lambda mode=None: {})
        shadow_publish(bus, "orpheus/detection/bird/events", det)
        assert bus.publish_timeouts == [1.0]

    def test_never_raises(self):
        bus = _FakeBus(streams=False)  # stream_publish raises
        det = SimpleNamespace(event_id="evt-1", model_dump=lambda mode=None: {})
        shadow_publish(bus, "orpheus/detection/bird/events", det)  # swallowed, no raise

    def test_topic_outside_stream_is_skipped_not_published(self):
        # A renamed output_topic would fail the stream's subject filter per-detection and
        # silently lose every write. Guard: skip cleanly (never touch stream_publish).
        import orpheus_common.event_sourcing as es

        es._WARNED_UNKNOWN_TOPICS.clear()
        bus = _FakeBus()
        det = SimpleNamespace(event_id="evt-1", model_dump=lambda mode=None: {})
        shadow_publish(bus, "orpheus/detection/renamed/events", det)
        assert bus.published == []  # not attempted against a subject the stream rejects
        assert "orpheus/detection/renamed/events" in es._WARNED_UNKNOWN_TOPICS

    def test_unknown_topic_warns_once(self, monkeypatch):
        import orpheus_common.event_sourcing as es

        es._WARNED_UNKNOWN_TOPICS.clear()
        calls: list = []
        monkeypatch.setattr(es.logger, "warning", lambda *a, **k: calls.append((a, k)))
        bus = _FakeBus()
        det = SimpleNamespace(event_id="e", model_dump=lambda mode=None: {})
        shadow_publish(bus, "orpheus/x/y/events", det)
        shadow_publish(bus, "orpheus/x/y/events", det)  # same topic again -> no new warning
        assert len(calls) == 1


@pytest.mark.parametrize("topic", DOMAIN_DETECTION_TOPICS)
def test_domain_topics_are_dot_free(topic):
    # Every domain topic AND its shadow subject must pass the durable-stream
    # dot-free guard (the shadow subject is what stream_publish validates).
    from orpheus_common.event_bus_nats import _require_dotfree_topic

    _require_dotfree_topic(topic)  # no raise
    _require_dotfree_topic(domain_subject(topic))  # no raise


class TestDomainSubject:
    def test_reroots_under_the_shadow_prefix(self):
        assert domain_subject("orpheus/detection/bird/events") == (
            "orpheus/domain/detection/bird/events"
        )
        assert domain_subject("orpheus/audio/motion/events") == (
            "orpheus/domain/audio/motion/events"
        )

    def test_disjoint_from_every_live_topic(self):
        shadows = {domain_subject(t) for t in DOMAIN_DETECTION_TOPICS}
        assert not shadows & set(DOMAIN_DETECTION_TOPICS)


@pytest.fixture(autouse=True)
def _reset_shadow_breaker():
    """The breaker is module state; isolate it per test."""
    event_sourcing._breaker_failures = 0
    event_sourcing._breaker_last_probe = 0.0
    event_sourcing._breaker_open_since = 0.0
    yield
    event_sourcing._breaker_failures = 0
    event_sourcing._breaker_last_probe = 0.0
    event_sourcing._breaker_open_since = 0.0


class TestShadowBreaker:
    def test_trips_after_consecutive_failures_then_probes_and_recovers(self):
        det = SimpleNamespace(event_id="e", model_dump=lambda mode=None: {})
        bus = _FakeBus()
        calls = {"n": 0}

        def failing(subject, payload, *, msg_id=None, timeout=None):
            calls["n"] += 1
            raise RuntimeError("broker down")

        bus.stream_publish = failing
        for _ in range(10):
            shadow_publish(bus, "orpheus/detection/bird/events", det)
        # Tripped at 5 consecutive failures; the remaining 5 were skipped
        # inside the probe window (no per-detection ack-timeout tax).
        assert calls["n"] == 5

        # After the probe interval, exactly one probe goes through (and fails).
        event_sourcing._breaker_last_probe -= 31.0
        shadow_publish(bus, "orpheus/detection/bird/events", det)
        shadow_publish(bus, "orpheus/detection/bird/events", det)
        assert calls["n"] == 6

        # A succeeding probe closes the breaker; normal flow resumes.
        def ok(subject, payload, *, msg_id=None, timeout=None):
            calls["n"] += 1

        bus.stream_publish = ok
        event_sourcing._breaker_last_probe -= 31.0
        shadow_publish(bus, "orpheus/detection/bird/events", det)
        shadow_publish(bus, "orpheus/detection/bird/events", det)
        assert calls["n"] == 8
        assert event_sourcing._breaker_failures == 0
