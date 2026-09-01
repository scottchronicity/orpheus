"""JetStream EventBus surfaces (ADR 0017): request-reply, KV, durable streams.

The additive contract (mqtt raises NotImplementedError) always runs. The real
JetStream round-trips run against a reachable nats-server (here + CI-with-nats),
and skip otherwise.
"""

import threading
import uuid

import pytest

from orpheus_common.event_bus_nats import NatsBus
from orpheus_common.mqtt import MQTTClient

NATS_URL = "nats://127.0.0.1:4222"


class TestOptionalSurfacesRaiseOnMqtt:
    """Additive contract: a non-JetStream backend raises, so call sites can
    feature-detect and nothing existing breaks."""

    def _bus(self):
        return MQTTClient(broker_host="localhost", client_id="t")

    def test_request_raises(self):
        with pytest.raises(NotImplementedError):
            self._bus().request("orpheus/q", {})

    def test_kv_raises(self):
        bus = self._bus()
        with pytest.raises(NotImplementedError):
            bus.kv_get("b", "k")
        with pytest.raises(NotImplementedError):
            bus.kv_put("b", "k", {"v": 1})
        with pytest.raises(NotImplementedError):
            bus.kv_delete("b", "k")
        with pytest.raises(NotImplementedError):
            bus.kv_watch("b", "*", lambda k, v: None)
        with pytest.raises(NotImplementedError):
            bus.kv_list("b")

    def test_streams_raise(self):
        bus = self._bus()
        with pytest.raises(NotImplementedError):
            bus.stream_ensure("s", ["orpheus/x"])
        with pytest.raises(NotImplementedError):
            bus.stream_publish("orpheus/x", {})
        with pytest.raises(NotImplementedError):
            bus.stream_replay("s", lambda t, p: None)


@pytest.fixture
def live_bus():
    bus = NatsBus(NATS_URL, client_id="jstest", connect_timeout=2.0)
    try:
        bus.connect()
    except Exception:
        pytest.skip(f"no nats-server on {NATS_URL}")
    yield bus
    bus.disconnect()


class TestJetStreamLive:
    def test_kv_roundtrip(self, live_bus):
        bucket = "t-" + uuid.uuid4().hex[:8]
        rev = live_bus.kv_put(bucket, "audio.gain", {"v": 0.5})
        assert isinstance(rev, int) and rev >= 1
        assert live_bus.kv_get(bucket, "audio.gain") == {"v": 0.5}
        assert live_bus.kv_get(bucket, "missing") is None
        live_bus.kv_delete(bucket, "audio.gain")
        assert live_bus.kv_get(bucket, "audio.gain") is None

    def test_kv_watch_fires(self, live_bus):
        bucket = "t-" + uuid.uuid4().hex[:8]
        seen = []
        ev = threading.Event()

        def _cb(key, value):
            seen.append((key, value))
            ev.set()

        live_bus.kv_watch(bucket, "config.x", _cb)
        live_bus.kv_put(bucket, "config.x", {"on": True})
        assert ev.wait(3), "kv_watch callback did not fire"
        assert ("config.x", {"on": True}) in seen

    def test_stream_replay_roundtrip(self, live_bus):
        stream = "T" + uuid.uuid4().hex[:8].upper()
        subj = f"orpheus/stream/{stream.lower()}/events"
        live_bus.stream_ensure(stream, [subj])
        for i in range(3):
            live_bus.stream_publish(subj, {"n": i})
        replayed = []
        count = live_bus.stream_replay(stream, lambda t, p: replayed.append(p))
        assert count == 3
        assert [r["n"] for r in replayed] == [0, 1, 2]  # oldest-first

    def test_stream_replay_empty_returns_zero(self, live_bus):
        # A drained/empty stream returns 0 via the fetch-timeout exit, not a hang.
        stream = "T" + uuid.uuid4().hex[:8].upper()
        subj = f"orpheus/stream/{stream.lower()}/events"
        live_bus.stream_ensure(stream, [subj])
        count = live_bus.stream_replay(stream, lambda t, p: None)
        assert count == 0

    def test_request_no_responder_raises_cleanly(self, live_bus):
        # No responder on the subject: request() must raise a clean, typed nats
        # error within ~timeout (not a FuturesTimeout, not a hang). Guards the
        # outer/inner timeout-layering fix (caller timeout would else cap at 5s).
        import asyncio

        import nats.errors

        with pytest.raises(
            (nats.errors.NoRespondersError, nats.errors.TimeoutError, asyncio.TimeoutError)
        ):
            live_bus.request("orpheus/q/nobody-home", {"x": 1}, timeout=0.5)


class TestRetainParityLive:
    """retain=True -> KV last-value; a late subscriber gets the current state."""

    def test_late_subscriber_gets_retained_value(self, live_bus):
        from orpheus_common.event_bus_nats import _RETAIN_BUCKET

        topic = f"orpheus/state/{uuid.uuid4().hex[:8]}/x"
        live_bus.publish(topic, {"v": 7}, retain=True)  # publish BEFORE subscribe
        seen = []
        ev = threading.Event()

        def cb(t, p):
            seen.append((t, p))
            ev.set()

        live_bus.subscribe(topic, cb)
        assert ev.wait(3), "retained value was not replayed to the late subscriber"
        assert seen[0] == (topic, {"v": 7})
        live_bus.kv_delete(_RETAIN_BUCKET, topic.replace("/", "."))  # test hygiene

    def test_retained_value_replays_through_wildcard(self, live_bus):
        from orpheus_common.event_bus_nats import _RETAIN_BUCKET

        prefix = f"orpheus/state/{uuid.uuid4().hex[:8]}"
        live_bus.publish(f"{prefix}/x", {"v": 1}, retain=True)
        seen = []
        ev = threading.Event()

        def cb(t, p):
            seen.append((t, p))
            ev.set()

        live_bus.subscribe(f"{prefix}/+", cb)
        assert ev.wait(3), "retained value not replayed to a wildcard subscriber"
        assert (f"{prefix}/x", {"v": 1}) in seen
        live_bus.kv_delete(_RETAIN_BUCKET, f"{prefix}.x")


class TestPresenceLive:
    """KV-TTL presence: a kill -9'd agent (stops refreshing) ages out within ttl;
    an explicit offline fires the watcher. The MQTT-LWT replacement."""

    def test_kv_survives_explicit_reconnect(self):
        # An explicit disconnect()+connect() must invalidate cached KV handles so
        # the second connection doesn't operate on a dead JetStream context.
        bus = NatsBus(NATS_URL, client_id="kvrc", connect_timeout=2.0)
        try:
            bus.connect()
        except Exception:
            pytest.skip(f"no nats-server on {NATS_URL}")
        try:
            bucket = "t-" + uuid.uuid4().hex[:8]
            bus.kv_put(bucket, "a", {"n": 1})
            bus.disconnect()
            bus.connect()
            assert bus.kv_get(bucket, "a") == {"n": 1}  # stale handle would error
            bus.kv_put(bucket, "a", {"n": 2})
            assert bus.kv_get(bucket, "a") == {"n": 2}
        finally:
            bus.disconnect()

    def test_kv_list_snapshots_live_keys(self, live_bus):
        bucket = "t-" + uuid.uuid4().hex[:8]
        assert live_bus.kv_list(bucket) == {}  # absent bucket -> empty
        live_bus.kv_put(bucket, "a", {"n": 1})
        live_bus.kv_put(bucket, "b", {"n": 2})
        assert live_bus.kv_list(bucket) == {"a": {"n": 1}, "b": {"n": 2}}
        live_bus.kv_delete(bucket, "a")
        assert live_bus.kv_list(bucket) == {"b": {"n": 2}}

    def test_presence_expires_after_ttl(self, live_bus):
        import time

        from orpheus_common.actor import Presence

        pres = Presence(live_bus, bucket="pres-" + uuid.uuid4().hex[:8], ttl=2.0)
        pres.online("agent-x", {"status": "online"})
        assert "agent-x" in pres.snapshot()
        # Stop refreshing (== kill -9): the key ages out within ttl -> offline.
        time.sleep(3.5)
        assert pres.snapshot() == {}

    def test_presence_offline_fires_watch(self, live_bus):
        from orpheus_common.actor import Presence

        pres = Presence(live_bus, bucket="pres-" + uuid.uuid4().hex[:8], ttl=60.0)
        # The PRODUCER's first write creates the bucket (fixing its bucket-wide
        # ttl); watchers are create=False — a watcher-created bucket would have
        # NO ttl and presence keys would never expire — so the watch attaches
        # only once a producer exists.
        pres.online("agent-y")
        events = []
        ev = threading.Event()

        def cb(agent_id, payload):
            events.append((agent_id, payload))
            ev.set()

        pres.watch(cb)
        pres.online("agent-y")  # refresh fires the watcher
        assert ev.wait(3), "presence online did not fire the watcher"
        assert ("agent-y", {"status": "online"}) in events
        ev.clear()
        pres.offline("agent-y")
        assert ev.wait(3), "presence offline did not fire the watcher"
        assert ("agent-y", None) in events

    def test_presence_watch_before_any_producer_does_not_create_bucket(self, live_bus):
        # A consumer watching FIRST must not create the bucket (bucket-wide ttl
        # is fixed at create — a watcher would set NO ttl, breaking expiry).
        from orpheus_common.actor import Presence

        bucket = "pres-" + uuid.uuid4().hex[:8]
        pres = Presence(live_bus, bucket=bucket, ttl=60.0)
        pres.watch(lambda k, v: None)  # bucket absent → watch no-ops, no create
        assert live_bus.kv_list(bucket) == {}  # still absent (kv_list won't create)
        # The first PRODUCER write creates it, with the producer's ttl.
        pres.online("agent-z")
        assert "agent-z" in pres.snapshot()


class TestStreamRetentionAndDedupLive:
    """Determinism-contract §4.1 + §4.4: bounded retention on stream_ensure and
    Nats-Msg-Id dedup on stream_publish — the prerequisites for a reversible,
    reconcilable domain shadow."""

    @staticmethod
    def _stream_info(bus, name):
        async def _op():
            return await bus._nc.jetstream().stream_info(name)

        return bus._submit(_op())

    def test_stream_ensure_applies_bounded_retention(self, live_bus):
        from nats.js.api import DiscardPolicy

        name = "S" + uuid.uuid4().hex[:8].upper()
        subj = f"orpheus/stream/{name.lower()}/events"
        live_bus.stream_ensure(
            name, [subj], max_age=120.0, max_bytes=1_000_000, discard="old"
        )
        cfg = self._stream_info(live_bus, name).config
        assert cfg.max_age == 120.0  # seconds, round-trips (nats-py converts ns<->s)
        assert cfg.max_bytes == 1_000_000
        assert cfg.discard == DiscardPolicy.OLD

    def test_stream_publish_msg_id_dedups(self, live_bus):
        name = "S" + uuid.uuid4().hex[:8].upper()
        subj = f"orpheus/stream/{name.lower()}/events"
        live_bus.stream_ensure(name, [subj], max_age=300.0, max_bytes=5_000_000, discard="old")
        live_bus.stream_publish(subj, {"n": 1}, msg_id="evt-1")
        live_bus.stream_publish(subj, {"n": 1}, msg_id="evt-1")  # same id -> deduped
        live_bus.stream_publish(subj, {"n": 2}, msg_id="evt-2")
        assert self._stream_info(live_bus, name).state.messages == 2  # dup dropped

    def test_stream_publish_rejects_dotted_subject(self, live_bus):
        # The dot-free guard fires before any broker work (fail-loud, sync).
        with pytest.raises(ValueError):
            live_bus.stream_publish("orpheus/state/v1.2/x", {"n": 1}, msg_id="x")
