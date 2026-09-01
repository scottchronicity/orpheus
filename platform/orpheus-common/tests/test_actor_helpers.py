"""Tests for the actor-model lifecycle helpers."""

import asyncio
import signal

from orpheus_common.actor import (
    ActorStats,
    HeartbeatPublisher,
    agent_identity,
    install_signal_handlers,
)
from orpheus_common.actor.clock import ManualClock


async def _settle(n: int = 3) -> None:
    for _ in range(n):
        await asyncio.sleep(0)


class TestAgentIdentity:
    def test_derives_canonical_identity(self) -> None:
        ident = agent_identity("crow-detection")
        assert ident.client_id == "orpheus-agent-crow-detection"
        assert ident.health_topic == "orpheus/system/crow-detection/health"
        assert ident.will_topic == ident.health_topic
        assert ident.will_payload == {"status": "offline"}

    def test_matches_correlator_literals(self) -> None:
        ident = agent_identity("event-correlator")
        assert ident.client_id == "orpheus-agent-event-correlator"
        assert ident.health_topic == "orpheus/system/event-correlator/health"

    def test_single_instance_default_unchanged(self) -> None:
        # instance_id None (default) must be byte-identical to the no-arg form.
        assert agent_identity("audio-motion") == agent_identity("audio-motion", None)
        assert agent_identity("audio-motion").instance_id is None

    def test_instance_id_makes_identity_unique(self) -> None:
        a = agent_identity("audio-motion", "host3-mic2")
        assert a.client_id == "orpheus-agent-audio-motion-host3-mic2"
        # per-type prefix kept so a type's instances group under .../<name>/+/health
        assert a.health_topic == "orpheus/system/audio-motion/host3-mic2/health"
        assert a.will_topic == a.health_topic
        assert a.instance_id == "host3-mic2"
        # two instances of the same type don't collide
        b = agent_identity("audio-motion", "host3-mic3")
        assert a.client_id != b.client_id
        assert a.health_topic != b.health_topic


class TestActorStats:
    def test_processed_and_dict(self) -> None:
        s = ActorStats()
        s.record_processed()
        s.record_processed(2)
        d = s.as_dict()
        assert d == {"events_processed": 3, "errors_count": 0, "last_error": None}

    def test_record_error_format(self) -> None:
        s = ActorStats()
        s.record_error(ValueError("boom"))
        assert s.errors_count == 1
        assert s.last_error == "ValueError: boom"

    def test_last_error_is_bounded(self) -> None:
        s = ActorStats()
        s.record_error(RuntimeError("x" * 500))
        # "<Type>: " + 200 chars of message
        assert s.last_error.startswith("RuntimeError: ")
        assert len(s.last_error.split(": ", 1)[1]) == 200


class _FakeBus:
    def __init__(self) -> None:
        self.published: list = []

    def publish(self, topic, payload) -> None:
        self.published.append((topic, payload))


class TestHeartbeatPublisher:
    def test_publishes_payload_each_interval(self) -> None:
        async def scenario() -> list:
            bus = _FakeBus()
            clock = ManualClock()
            seq = {"n": 0}

            def payload():
                seq["n"] += 1
                return {"status": "online", "tick": seq["n"]}

            hb = HeartbeatPublisher(
                bus, "orpheus/system/x/health", payload, interval=30.0, clock=clock
            )
            hb.start()
            await _settle()
            for _ in range(2):
                clock.advance(30)
                await _settle()
            await hb.stop()
            return bus.published

        published = asyncio.run(scenario())
        assert published == [
            ("orpheus/system/x/health", {"status": "online", "tick": 1}),
            ("orpheus/system/x/health", {"status": "online", "tick": 2}),
        ]


class _RecordingLoop:
    def __init__(self) -> None:
        self.handlers: dict = {}

    def add_signal_handler(self, sig, cb) -> None:
        self.handlers[sig] = cb


class _UnsupportedLoop:
    def add_signal_handler(self, sig, cb) -> None:
        raise NotImplementedError("signals only work on the main thread")


class _FakeEvent:
    """Stand-in for asyncio.Event (which needs a running loop to construct on 3.9);
    install_signal_handlers only wires `.set` as the signal callback."""

    def __init__(self) -> None:
        self.is_set = False

    def set(self) -> None:
        self.is_set = True


class TestInstallSignalHandlers:
    def test_wires_sigint_sigterm_to_stop(self) -> None:
        loop = _RecordingLoop()
        ev = _FakeEvent()
        install_signal_handlers(loop, ev)
        assert set(loop.handlers) == {signal.SIGINT, signal.SIGTERM}
        loop.handlers[signal.SIGINT]()  # invoking the handler sets the event
        assert ev.is_set

    def test_tolerates_unsupported_loop(self) -> None:
        # Non-main-thread / unsupported loop: logs + skips, does not raise.
        install_signal_handlers(_UnsupportedLoop(), _FakeEvent())
