"""Tests for the NATS EventBus backend (pub/sub parity; JetStream surfaces TBD).

Uses an injected fake nats client so the REAL thread+loop+dispatch bridge is
exercised without a broker or nats-py installed.
"""

import asyncio
import sys
import threading
import time
import types
from unittest import mock

import pytest

from orpheus_common import event_bus_nats
from orpheus_common.config import EventBusConfig, OrpheusConfig
from orpheus_common.event_bus import create_event_bus
from orpheus_common.event_bus_nats import (
    NatsBus,
    _require_dotfree_topic,
    mqtt_to_nats_subject,
    nats_to_mqtt_topic,
)


class _FakeMsg:
    def __init__(self, subject: str, data: bytes) -> None:
        self.subject = subject
        self.data = data
        self.reply = ""


class _FakeSub:
    def __init__(self) -> None:
        self.unsubscribed = False

    async def unsubscribe(self) -> None:
        self.unsubscribed = True


class _FakeNats:
    """Records calls; lets a test deliver a message to a stored handler."""

    def __init__(self, fail_subscribes: int = 0) -> None:
        self.published: list = []
        self.cbs: dict = {}
        self.sub_calls: list = []  # every broker subscribe (dup-subscribe guard)
        self.subs_returned: list = []  # the _FakeSub handles handed out
        self.is_connected = True
        self.drained = False
        self.closed = False
        self.fail_subscribes = fail_subscribes  # reject this many subscribes first

    async def publish(self, subject: str, data: bytes) -> None:
        self.published.append((subject, data))

    async def subscribe(self, subject: str, cb=None) -> _FakeSub:
        if self.fail_subscribes > 0:
            self.fail_subscribes -= 1
            self.sub_calls.append(subject)
            raise ConnectionError("subscribe rejected")
        self.cbs[subject] = cb
        self.sub_calls.append(subject)
        sub = _FakeSub()
        self.subs_returned.append(sub)
        return sub

    async def drain(self) -> None:
        self.drained = True

    async def close(self) -> None:
        self.closed = True


class _Recorder:
    """A subscriber callback that records deliveries and signals an Event, so a
    test can wait for the off-loop dispatch thread to deliver."""

    def __init__(self) -> None:
        self.items: list = []
        self._ev = threading.Event()

    def __call__(self, topic, payload) -> None:
        self.items.append((topic, payload))
        self._ev.set()

    def wait(self, timeout: float = 2.0) -> bool:
        return self._ev.wait(timeout)


def _bus(fake: _FakeNats, **kw) -> NatsBus:
    async def _factory():
        return fake

    return NatsBus("nats://test:4222", client_id="t", connect_coro_factory=_factory, **kw)


def _deliver(bus: NatsBus, handler, subject: str, data: bytes) -> None:
    """Run a subscription handler on the bus loop (as nats would). The handler
    decodes + enqueues; the dispatch thread then calls the user callback."""
    fut = asyncio.run_coroutine_threadsafe(handler(_FakeMsg(subject, data)), bus._loop)
    fut.result(timeout=2)


def _wait_until(pred, timeout: float = 2.0, interval: float = 0.01) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(interval)
    return pred()


class TestTopicTranslation:
    def test_mqtt_to_nats(self) -> None:
        assert mqtt_to_nats_subject("orpheus/detection/bird/events") == (
            "orpheus.detection.bird.events"
        )
        assert mqtt_to_nats_subject("orpheus/system/+/health") == "orpheus.system.*.health"
        assert mqtt_to_nats_subject("orpheus/#") == "orpheus.>"

    def test_nats_to_mqtt(self) -> None:
        assert nats_to_mqtt_topic("orpheus.entities.animal") == "orpheus/entities/animal"


class TestNatsBusLifecycle:
    def test_connect_disconnect(self) -> None:
        fake = _FakeNats()
        bus = _bus(fake)
        bus.connect()
        try:
            assert bus.is_connected is True
        finally:
            bus.disconnect()
        assert fake.drained is True and fake.closed is True
        assert bus.is_connected is False

    def test_publish_translates_and_json_encodes(self) -> None:
        fake = _FakeNats()
        bus = _bus(fake)
        bus.connect()
        try:
            bus.publish("orpheus/detection/bird/events", {"a": 1})
        finally:
            bus.disconnect()
        assert fake.published == [("orpheus.detection.bird.events", b'{"a": 1}')]

    def test_retain_stores_best_effort_and_qos_warns_but_still_publishes(self) -> None:
        fake = _FakeNats()
        bus = _bus(fake)
        bus.connect()
        try:
            bus.publish("orpheus/state/x", {"v": 1}, qos=1, retain=True)
        finally:
            bus.disconnect()
        # qos has no NATS analogue (one-time warn); retain mirrors to KV best-effort
        # (the fake has no jetstream, so the store fails) — but the LIVE message still
        # goes out either way. (Live KV retain replay is in test_event_bus_jetstream.)
        assert fake.published == [("orpheus.state.x", b'{"v": 1}')]
        assert bus._warned_qos is True

    def test_publish_before_connect_is_noop(self) -> None:
        fake = _FakeNats()
        bus = _bus(fake)
        # Not connected → best-effort no-op (matches MQTT), not a crash.
        bus.publish("orpheus/x", {"a": 1})
        assert fake.published == []

    def test_subscribe_delivers_translated_topic_and_decoded_payload(self) -> None:
        fake = _FakeNats()
        bus = _bus(fake)
        bus.connect()
        rec = _Recorder()
        try:
            bus.subscribe("orpheus/system/+/health", rec)
            handler = fake.cbs["orpheus.system.*.health"]
            _deliver(bus, handler, "orpheus.system.bird-detection.health", b'{"status": "online"}')
            assert rec.wait()
        finally:
            bus.disconnect()
        assert rec.items == [("orpheus/system/bird-detection/health", {"status": "online"})]

    def test_subscribe_before_connect_is_buffered_then_flushed(self) -> None:
        # 5 real agents subscribe BEFORE connect; the nats backend must support it.
        fake = _FakeNats()
        bus = _bus(fake)
        rec = _Recorder()
        bus.subscribe("orpheus/x", rec)
        assert "orpheus.x" not in fake.cbs  # buffered, not yet sent to nats
        bus.connect()
        try:
            assert "orpheus.x" in fake.cbs  # flushed on connect
            _deliver(bus, fake.cbs["orpheus.x"], "orpheus.x", b'{"ok": 1}')
            assert rec.wait()
        finally:
            bus.disconnect()
        assert rec.items == [("orpheus/x", {"ok": 1})]

    def test_bad_message_does_not_kill_subscription(self) -> None:
        fake = _FakeNats()
        bus = _bus(fake)
        bus.connect()
        rec = _Recorder()
        try:
            bus.subscribe("orpheus/x", rec)
            handler = fake.cbs["orpheus.x"]
            _deliver(bus, handler, "orpheus.x", b"not-json")  # swallowed, no enqueue
            _deliver(bus, handler, "orpheus.x", b'{"ok": 1}')  # still delivers
            assert rec.wait()
        finally:
            bus.disconnect()
        assert rec.items == [("orpheus/x", {"ok": 1})]

    def test_unsubscribe(self) -> None:
        fake = _FakeNats()
        bus = _bus(fake)
        bus.connect()
        try:
            bus.subscribe("orpheus/x", lambda t, p: None)
            assert "orpheus.x" in bus._subs
            bus.unsubscribe("orpheus/x")
            assert "orpheus.x" not in bus._subs
        finally:
            bus.disconnect()

    def test_repeat_subscribe_fans_out_without_second_broker_subscription(self) -> None:
        # MQTTClient parity: subscribing the SAME topic twice must register both
        # callbacks behind ONE broker subscription — the old code replaced the
        # entry, orphaning a live subscription that kept delivering to the stale
        # callback forever and double-subscribing the subject.
        fake = _FakeNats()
        bus = _bus(fake)
        bus.connect()
        rec_a, rec_b = _Recorder(), _Recorder()
        try:
            bus.subscribe("orpheus/x", rec_a)
            bus.subscribe("orpheus/x", rec_b)
            assert fake.sub_calls == ["orpheus.x"]  # exactly ONE broker subscription
            _deliver(bus, fake.cbs["orpheus.x"], "orpheus.x", b'{"n": 1}')
            assert rec_a.wait() and rec_b.wait()
        finally:
            bus.disconnect()
        # Both callbacks got the message exactly once (fan-out, no duplicates).
        assert rec_a.items == [("orpheus/x", {"n": 1})]
        assert rec_b.items == [("orpheus/x", {"n": 1})]

    def test_unsubscribe_drops_all_callbacks_and_the_single_handle(self) -> None:
        fake = _FakeNats()
        bus = _bus(fake)
        bus.connect()
        try:
            bus.subscribe("orpheus/x", lambda t, p: None)
            bus.subscribe("orpheus/x", lambda t, p: None)
            bus.unsubscribe("orpheus/x")
            assert "orpheus.x" not in bus._subs
            # The one live broker handle was actually unsubscribed (not leaked).
            assert [s.unsubscribed for s in fake.subs_returned] == [True]
        finally:
            bus.disconnect()

    def test_connect_failure_propagates_and_clears_state(self) -> None:
        async def _boom():
            raise ConnectionError("no broker")

        bus = NatsBus(
            "nats://nope:4222", client_id="t", connect_coro_factory=_boom, connect_timeout=2.0
        )
        with pytest.raises(ConnectionError):
            bus.connect()
        # C1: no stale loop left behind, so a later publish no-ops instead of wedging.
        assert bus._loop is None
        assert bus.is_connected is False


class TestColdBrokerHardening:
    def test_server_list_comma_splits_for_failover(self) -> None:
        bus = NatsBus("nats://a:4222, nats://b:4222 ,nats://c:4222", client_id="t")
        assert bus._server_list() == ["nats://a:4222", "nats://b:4222", "nats://c:4222"]
        # the common single-url case is unchanged
        assert NatsBus("nats://h:4222", client_id="t")._server_list() == ["nats://h:4222"]

    def test_connect_required_true_still_raises_on_cold_broker(self) -> None:
        # Default behavior is unchanged: a cold broker at connect() is fatal.
        async def _boom():
            raise ConnectionError("cold")

        bus = NatsBus(
            "nats://nope:4222", client_id="t", connect_coro_factory=_boom, connect_timeout=2.0
        )
        with pytest.raises(ConnectionError):
            bus.connect()
        assert bus._loop is None and bus.is_connected is False

    def test_nonfatal_comes_up_disconnected_then_attaches_and_flushes(self) -> None:
        fake = _FakeNats()
        calls = {"n": 0}

        async def _flaky():
            # Cold for the first two attempts, then the broker "appears".
            calls["n"] += 1
            if calls["n"] < 3:
                raise ConnectionError("cold")
            return fake

        bus = NatsBus(
            "nats://nope:4222",
            client_id="t",
            connect_coro_factory=_flaky,
            connect_required=False,
            reconnect_time_wait=0.02,
            connect_timeout=2.0,
        )
        rec = _Recorder()
        bus.subscribe("orpheus/x", rec)  # buffered before any connection exists
        bus.connect()  # must NOT raise though the broker is cold
        try:
            assert bus.is_connected is False  # came up disconnected
            bus.publish("orpheus/x", {"a": 1})  # best-effort no-op while down, no raise
            # The background retry loop attaches once _flaky starts returning.
            assert _wait_until(lambda: bus.is_connected), "retry never attached"
            # The buffered subscription was flushed on attach (no _submit deadlock).
            assert "orpheus.x" in fake.cbs
            _deliver(bus, fake.cbs["orpheus.x"], "orpheus.x", b'{"a": 1}')
            assert rec.wait(2.0)
            assert rec.items == [("orpheus/x", {"a": 1})]
        finally:
            bus.disconnect()
        assert bus.is_connected is False
        # The retry-attached connection is drained+closed on disconnect (not leaked).
        assert fake.drained is True and fake.closed is True

    def test_nonfatal_disconnect_while_still_cold_is_clean(self) -> None:
        # Broker never appears; disconnect() must cancel the retry loop cleanly.
        async def _never():
            raise ConnectionError("cold")

        bus = NatsBus(
            "nats://nope:4222",
            client_id="t",
            connect_coro_factory=_never,
            connect_required=False,
            reconnect_time_wait=0.02,
            connect_timeout=2.0,
        )
        bus.connect()
        assert bus.is_connected is False
        bus.disconnect()  # no hang, no leaked thread
        assert bus._thread is None and bus._loop is None


class TestConnectAttemptIsBounded:
    """nats-py does not fail fast on a cold broker: with allow_reconnect it sits
    in its own retry loop and nats.connect never returns. Every await of the
    connect factory therefore has to be bounded, or the two paths that are
    supposed to survive a cold broker never run at all."""

    def test_hung_connect_takes_the_nonfatal_path_instead_of_raising(self) -> None:
        # The production shape: the UI starts before the backplane, the connect
        # hangs, and the UI must come up disconnected + retrying — NOT drop the
        # bus and serve stale cache for the life of the process.
        fake = _FakeNats()
        calls = {"n": 0}

        async def _hangs_then_attaches():
            calls["n"] += 1
            if calls["n"] == 1:
                await asyncio.sleep(30)  # nats-py's internal retry loop
            return fake

        rec = _Recorder()
        bus = NatsBus(
            "nats://cold:4222",
            client_id="t",
            connect_coro_factory=_hangs_then_attaches,
            connect_required=False,
            connect_timeout=0.1,
            reconnect_time_wait=0.02,
        )
        bus.subscribe("orpheus/x", rec)
        bus.connect()  # must return, not raise, not block for 30s
        try:
            assert _wait_until(lambda: bus.is_connected), "never attached after the hang"
            assert _wait_until(lambda: bus.subscription_status()["pending"] == [])
            _deliver(bus, fake.cbs["orpheus.x"], "orpheus.x", b'{"a": 1}')
            assert rec.wait(2.0)
            assert rec.items == [("orpheus/x", {"a": 1})]
        finally:
            bus.disconnect()

    def test_hung_connect_still_raises_connectionerror_when_required(self) -> None:
        # connect_required=True keeps failing loudly, and fails at the deadline
        # rather than hanging the caller forever.
        async def _hangs():
            await asyncio.sleep(30)

        bus = NatsBus(
            "nats://cold:4222",
            client_id="t",
            connect_coro_factory=_hangs,
            connect_timeout=0.1,
        )
        started = time.monotonic()
        with pytest.raises(ConnectionError):
            bus.connect()
        assert time.monotonic() - started < 5.0, "connect() hung past its deadline"
        assert bus._loop is None and bus.is_connected is False

    def test_retry_loop_survives_a_hung_attempt(self) -> None:
        # A hung attempt inside the background retry loop must not wedge it:
        # otherwise the loop blocks on iteration one and never tries again.
        fake = _FakeNats()
        calls = {"n": 0}

        async def _hang_twice():
            calls["n"] += 1
            if calls["n"] <= 2:
                await asyncio.sleep(30)
            return fake

        bus = NatsBus(
            "nats://cold:4222",
            client_id="t",
            connect_coro_factory=_hang_twice,
            connect_required=False,
            connect_timeout=0.1,
            reconnect_time_wait=0.02,
        )
        bus.connect()
        try:
            assert _wait_until(
                lambda: bus.is_connected, timeout=5.0
            ), "the retry loop wedged on a hung attempt"
            assert calls["n"] >= 3  # it really did keep retrying
        finally:
            bus.disconnect()


class TestSubscriptionRecovery:
    """A bus that is connected but subscribed to nothing is the worst failure
    mode this backend has: every consumer looks healthy and serves stale data
    forever. These cover the paths that make a lost subscription recoverable
    and visible."""

    def test_status_shows_pending_while_unattached_then_subscribed(self) -> None:
        fake = _FakeNats()
        bus = _bus(fake)
        bus.subscribe("orpheus/x", lambda t, p: None)  # buffered, no connection yet
        assert bus.subscription_status() == {
            "connected": False,
            "subscribed": [],
            "pending": ["orpheus.x"],
            "requested": 1,
        }
        bus.connect()
        try:
            assert _wait_until(lambda: bus.subscription_status()["subscribed"] == ["orpheus.x"])
            assert bus.subscription_status()["pending"] == []
        finally:
            bus.disconnect()

    def test_subscribe_rejected_while_connected_is_retried_by_watchdog(self) -> None:
        # The incident: the connection is up, the broker refuses the registration,
        # and nothing ever tries again — the consumer runs blind but "healthy".
        fake = _FakeNats(fail_subscribes=1)
        bus = _bus(fake, reconnect_time_wait=0.02)
        bus.connect()
        rec = _Recorder()
        try:
            bus.subscribe("orpheus/x", rec)
            # It is registered locally but the broker never accepted it, and the
            # bus says so instead of reporting a healthy connection.
            assert _wait_until(lambda: bus.subscription_status()["pending"] == ["orpheus.x"])
            assert bus.subscription_status()["connected"] is True
            # The sweep re-applies it without a reconnect or a restart.
            assert _wait_until(
                lambda: bus.subscription_status()["subscribed"] == ["orpheus.x"], timeout=5.0
            ), "watchdog never re-applied the rejected subscription"
            _deliver(bus, fake.cbs["orpheus.x"], "orpheus.x", b'{"a": 1}')
            assert rec.wait(2.0)
            assert rec.items == [("orpheus/x", {"a": 1})]
        finally:
            bus.disconnect()

    def test_a_permanently_refused_subject_warns_once_not_every_sweep(self) -> None:
        # A subject the broker never accepts is swept forever; warning on each
        # pass is how a service fills a disk with its own logs.
        fake = _FakeNats(fail_subscribes=10_000)
        bus = _bus(fake, reconnect_time_wait=0.02)
        bus.connect()
        warnings: list = []
        try:
            with mock.patch.object(
                event_bus_nats.logger,
                "warning",
                side_effect=lambda msg, **kw: warnings.append(msg),
            ):
                bus.subscribe("orpheus/x", lambda t, p: None)
                assert _wait_until(lambda: fake.sub_calls.count("orpheus.x") >= 4, timeout=5.0)
                unregistered = [m for m in warnings if "still not registered" in m]
                assert len(unregistered) == 1, unregistered
        finally:
            bus.disconnect()

    def test_a_subject_that_recovers_can_warn_again_on_the_next_outage(self) -> None:
        # The once-only warning is per outage, not for the life of the process:
        # a subject that comes back and later drops again must still be visible.
        fake = _FakeNats(fail_subscribes=1)
        bus = _bus(fake, reconnect_time_wait=0.02)
        bus.connect()
        try:
            bus.subscribe("orpheus/x", lambda t, p: None)
            assert _wait_until(
                lambda: bus.subscription_status()["subscribed"] == ["orpheus.x"], timeout=5.0
            )
            assert bus._sub_warned == set(), "a restored subject stayed marked as warned"
        finally:
            bus.disconnect()

    def test_watchdog_does_not_resubscribe_live_subjects(self) -> None:
        # The sweep must be a no-op when everything is healthy, or it would pile
        # up duplicate broker subscriptions (and duplicate deliveries) over time.
        fake = _FakeNats()
        bus = _bus(fake, reconnect_time_wait=0.02)
        bus.connect()
        try:
            bus.subscribe("orpheus/x", lambda t, p: None)
            assert _wait_until(lambda: fake.sub_calls == ["orpheus.x"])
            time.sleep(0.3)  # several watchdog intervals
            assert fake.sub_calls == ["orpheus.x"]
        finally:
            bus.disconnect()

    def test_reconnect_callback_reapplies_subscriptions_nats_never_accepted(
        self, monkeypatch
    ) -> None:
        # nats-py restores the subscriptions it registered itself; one it never
        # accepted is invisible to it, so the bus has to re-apply it by hand.
        fake = _FakeNats()
        captured: dict = {}

        async def _fake_connect(**kw):
            captured.update(kw)
            return fake

        monkeypatch.setitem(sys.modules, "nats", types.SimpleNamespace(connect=_fake_connect))
        bus = NatsBus("nats://test:4222", client_id="t")  # real _default_connect path
        bus.connect()
        try:
            bus.subscribe("orpheus/x", lambda t, p: None)
            assert _wait_until(lambda: "orpheus.x" in fake.cbs)
            fake.cbs.clear()
            bus._subs["orpheus.x"]["handle"] = None  # the subscription nats lost
            fut = asyncio.run_coroutine_threadsafe(captured["reconnected_cb"](), bus._loop)
            fut.result(timeout=2)
            assert "orpheus.x" in fake.cbs
            assert bus.subscription_status()["pending"] == []
        finally:
            bus.disconnect()

    def test_cold_broker_retry_ends_genuinely_subscribed(self) -> None:
        # The regression the UI hit: connect() times out against a cold broker,
        # the background retry attaches later, and the consumer must end up
        # actually receiving messages — not merely "connected".
        fake = _FakeNats()
        calls = {"n": 0}

        async def _flaky():
            calls["n"] += 1
            if calls["n"] < 2:
                raise ConnectionError("cold")
            return fake

        bus = NatsBus(
            "nats://nope:4222",
            client_id="t",
            connect_coro_factory=_flaky,
            connect_required=False,
            reconnect_time_wait=0.02,
            connect_timeout=2.0,
        )
        rec = _Recorder()
        bus.subscribe("orpheus/health/x", rec)
        bus.connect()
        try:
            assert _wait_until(lambda: bus.is_connected)
            status = None
            assert _wait_until(lambda: bus.subscription_status()["pending"] == [])
            status = bus.subscription_status()
            assert status["subscribed"] == ["orpheus.health.x"]
            _deliver(bus, fake.cbs["orpheus.health.x"], "orpheus.health.x", b'{"ok": true}')
            assert rec.wait(2.0)
            assert rec.items == [("orpheus/health/x", {"ok": True})]
        finally:
            bus.disconnect()


class TestEventBusFactory:
    def test_eventbusconfig_nats_url_default_and_override(self) -> None:
        assert EventBusConfig.from_dict({}).nats_url == "nats://127.0.0.1:4222"
        c = EventBusConfig.from_dict({"backend": "nats", "nats_url": "nats://h:4222"})
        assert c.backend == "nats" and c.nats_url == "nats://h:4222"

    def test_create_event_bus_builds_nats(self) -> None:
        cfg = OrpheusConfig.from_dict(
            {
                "mqtt": {"broker_host": "localhost"},
                "event_bus": {"backend": "nats", "nats_url": "nats://x:4222"},
            },
            source="<test>",
        )
        bus = create_event_bus(cfg, client_id="t")  # constructs, does not connect
        assert isinstance(bus, NatsBus)


class TestDispatchBackpressure:
    """The dispatch queue is bounded (paho had TCP backpressure; unbounded would
    grow without bound on the Jetson when a callback is slower than its topic).
    Policy on full: drop-OLDEST with a counter; the shutdown sentinel survives."""

    def test_full_queue_drops_oldest_and_counts(self) -> None:
        import queue as queue_mod

        bus = _bus(_FakeNats())  # not connected: dispatch worker not draining
        bus._dispatch_q = queue_mod.Queue(maxsize=2)
        for i in range(4):
            bus._dispatch_enqueue(("cb", "orpheus/x", i))
        assert bus.dispatch_stats() == {"queue_depth": 2, "dropped": 2}
        kept = [bus._dispatch_q.get_nowait()[2] for _ in range(2)]
        assert kept == [2, 3]  # oldest dropped, freshest kept

    def test_shutdown_sentinel_is_never_dropped(self) -> None:
        import queue as queue_mod

        from orpheus_common.event_bus_nats import _DISPATCH_SHUTDOWN

        bus = _bus(_FakeNats())
        bus._dispatch_q = queue_mod.Queue(maxsize=1)
        bus._dispatch_q.put_nowait(_DISPATCH_SHUTDOWN)
        bus._dispatch_enqueue(("cb", "orpheus/x", 1))  # full; must drop the NEW item
        assert bus._dispatch_q.get_nowait() is _DISPATCH_SHUTDOWN
        assert bus.dispatch_stats()["dropped"] == 1


class _FakeJsMsg:
    def __init__(self, subject: str, data: bytes) -> None:
        self.subject = subject
        self.data = data
        self.acked = False

    async def ack(self) -> None:
        self.acked = True


class _FakePullSub:
    """One batch of messages, then the drained-timeout exit."""

    def __init__(self, msgs: list, *, pending_after_drain: int = 0) -> None:
        self._batches = [msgs] if msgs else []
        # What consumer_info reports once fetch starts timing out: 0 models a
        # genuine drain; >0 models a silent broker with messages still queued.
        self._pending_after_drain = pending_after_drain

    async def fetch(self, batch: int, timeout: float) -> list:
        if self._batches:
            return self._batches.pop(0)
        from nats.errors import TimeoutError as NatsTimeoutError

        raise NatsTimeoutError

    async def consumer_info(self):
        remaining = sum(len(b) for b in self._batches) + self._pending_after_drain

        class _Info:
            num_pending = remaining

        return _Info()

    async def unsubscribe(self) -> None:
        pass


class _FakeNatsWithJs(_FakeNats):
    def __init__(self, js) -> None:
        super().__init__()
        self._js = js

    def jetstream(self):
        return self._js


class TestStreamReplayDispatch:
    """stream_replay must run the user callback OFF the bus I/O loop (executor
    thread): inline it would deadlock any nested bus call (_submit waits on the
    loop the callback is holding) and stall keepalive/reconnect for the drain."""

    def test_callback_runs_off_loop_and_nested_bus_calls_do_not_deadlock(self) -> None:
        import json as json_mod

        class _Js:
            def __init__(self, msgs):
                self._msgs = msgs

            async def pull_subscribe(self, subj, stream=None):
                return _FakePullSub(self._msgs)

        msgs = [
            _FakeJsMsg("orpheus.stream.t.events", json_mod.dumps({"n": i}).encode())
            for i in range(3)
        ]
        fake = _FakeNatsWithJs(_Js(msgs))
        bus = _bus(fake)
        bus.connect()
        seen: list = []

        def cb(topic, payload):
            seen.append((threading.current_thread().name, topic, payload))
            # The nested bus call is the deadlock probe: inline on the loop this
            # would block _submit on the very loop running the replay coroutine.
            bus.publish("orpheus/nested", {"n": payload["n"]})

        try:
            count = bus.stream_replay("S", cb)
        finally:
            bus.disconnect()
        assert count == 3
        # Strict order preserved; every delivery off the bus loop/dispatch threads.
        assert [p["n"] for _, _, p in seen] == [0, 1, 2]
        assert all(not name.startswith("natsbus") for name, _, _ in seen)
        # All three nested publishes made it out (no deadlock, no timeout).
        nested = [s for s, _ in fake.published if s == "orpheus.nested"]
        assert len(nested) == 3
        assert all(m.acked for m in msgs)


class TestStreamEnsureDivergence:
    """A 10058 (stream exists) with a DIVERGING requested config must WARN with
    both sides — the requested config silently never applies — and stay at debug
    when the existing config matches."""

    def _ensure(self, existing_cfg, monkeypatch, **kwargs):
        from types import SimpleNamespace

        from nats.js.errors import APIError

        import orpheus_common.event_bus_nats as ebn

        class _Js:
            async def add_stream(self, name=None, subjects=None, **kw):
                raise APIError(err_code=10058, description="stream name already in use")

            async def stream_info(self, name):
                return SimpleNamespace(config=existing_cfg)

        warnings: list = []
        monkeypatch.setattr(
            ebn.logger, "warning", lambda msg, **kw: warnings.append((msg, kw))
        )
        bus = _bus(_FakeNatsWithJs(_Js()))
        bus.connect()
        try:
            bus.stream_ensure("S", ["orpheus/x/events"], **kwargs)
        finally:
            bus.disconnect()
        return warnings

    def test_diverging_retention_warns_with_both_configs(self, monkeypatch) -> None:
        from types import SimpleNamespace

        existing = SimpleNamespace(
            subjects=["orpheus.x.events"], max_age=120.0, max_bytes=None, discard=None
        )
        warnings = self._ensure(existing, monkeypatch, max_age=999.0)
        assert len(warnings) == 1
        msg, kw = warnings[0]
        assert "diverges" in msg
        assert kw["diverged"]["max_age"] == {"existing": 120.0, "requested": 999.0}

    def test_matching_config_stays_quiet(self, monkeypatch) -> None:
        from types import SimpleNamespace

        existing = SimpleNamespace(
            subjects=["orpheus.x.events"], max_age=120.0, max_bytes=None, discard=None
        )
        warnings = self._ensure(existing, monkeypatch, max_age=120.0)
        assert warnings == []  # idempotent re-ensure — debug only

    def test_subject_mismatch_warns(self, monkeypatch) -> None:
        from types import SimpleNamespace

        existing = SimpleNamespace(
            subjects=["orpheus.OTHER.events"], max_age=None, max_bytes=None, discard=None
        )
        warnings = self._ensure(existing, monkeypatch)
        assert len(warnings) == 1
        assert "subjects" in warnings[0][1]["diverged"]


class TestStreamPublishTimeout:
    """stream_publish threads an explicit ack budget to _submit so a hot-path
    caller (the event-sourcing shadow) can cap a brownout stall below op_timeout."""

    def test_explicit_timeout_reaches_submit(self) -> None:
        bus = _bus(_FakeNats())
        calls: list = []

        def spy(coro, **kw):
            coro.close()
            calls.append(kw)

        bus._submit = spy  # type: ignore[method-assign]
        bus._nc = object()  # satisfy the attach guard; _submit is stubbed anyway
        bus.stream_publish("orpheus/x/events", {"n": 1}, msg_id="e1", timeout=1.0)
        bus.stream_publish("orpheus/x/events", {"n": 2}, msg_id="e2")  # default budget
        assert calls == [{"timeout": 1.0}, {}]


class TestKvTtlDivergenceWarning:
    """Attaching to an EXISTING bucket with a requested ttl: warn loudly (with
    both windows) only when the bucket's real ttl differs — the requested ttl is
    a wire no-op, and a writer refreshing slower than the real window flaps."""

    def _kv_put(self, bucket_ttl, requested_ttl, monkeypatch):
        from types import SimpleNamespace

        import orpheus_common.event_bus_nats as ebn

        class _Handle:
            async def status(self):
                return SimpleNamespace(ttl=bucket_ttl)

            async def put(self, key, value):
                return 1

        class _Js:
            async def key_value(self, bucket):
                return _Handle()

        warnings: list = []
        monkeypatch.setattr(
            ebn.logger, "warning", lambda msg, **kw: warnings.append((msg, kw))
        )
        bus = _bus(_FakeNatsWithJs(_Js()))
        bus.connect()
        try:
            bus.kv_put("orpheus_presence", "agent-a", {"v": 1}, ttl=requested_ttl)
        finally:
            bus.disconnect()
        return warnings

    def test_diverging_ttl_warns_with_both_windows(self, monkeypatch) -> None:
        warnings = self._kv_put(90.0, 360.0, monkeypatch)
        assert len(warnings) == 1
        msg, kw = warnings[0]
        assert "DIFFERENT" in msg
        assert kw["requested_ttl"] == 360.0 and kw["bucket_ttl"] == 90.0

    def test_matching_ttl_is_silent(self, monkeypatch) -> None:
        assert self._kv_put(90.0, 90.0, monkeypatch) == []


class TestDotFreeTopicGuard:
    """The durable-stream subject invariant (determinism contract §4.2): a published
    stream subject must round-trip mqtt->nats->mqtt, so levels are [a-z0-9_-]+."""

    @pytest.mark.parametrize(
        "topic",
        [
            "orpheus/detection/audio/events",
            "orpheus/audio/motion/events",
            "orpheus/detection/bird/events",
            "single",
        ],
    )
    def test_accepts_clean_topics_and_they_round_trip(self, topic):
        _require_dotfree_topic(topic)  # no raise
        assert nats_to_mqtt_topic(mqtt_to_nats_subject(topic)) == topic

    @pytest.mark.parametrize(
        "topic",
        [
            "orpheus/state/v1.2/x",   # dot inside a level -> mis-routes
            "orpheus/detection/+/events",  # mqtt single-level wildcard
            "orpheus/detection/#",    # mqtt multi-level wildcard
            "Orpheus/Detection",      # uppercase (not in the frozen grammar)
            "orpheus/detection events",  # space
        ],
    )
    def test_rejects_non_roundtrip_topics(self, topic):
        with pytest.raises(ValueError):
            _require_dotfree_topic(topic)


class TestColdBrokerSurfaceContract:
    """A not-yet-attached bus must raise ConnectionError from the JetStream
    surfaces — never AttributeError, which feature-detection reads as "the
    backend has no such surface" and permanently disables consumers."""

    def _cold_bus(self) -> NatsBus:
        async def _never():
            raise ConnectionError("cold")

        bus = NatsBus(
            "nats://nope:4222",
            client_id="t",
            connect_coro_factory=_never,
            connect_required=False,
            reconnect_time_wait=5.0,  # keep the retry quiet during the test
            connect_timeout=2.0,
        )
        bus.connect()
        assert bus.is_connected is False
        return bus

    def test_surfaces_raise_connection_error_not_attribute_error(self) -> None:
        bus = self._cold_bus()
        try:
            for op in (
                lambda: bus.kv_list("b"),
                lambda: bus.kv_get("b", "k"),
                lambda: bus.kv_put("b", "k", {}),
                lambda: bus.kv_delete("b", "k"),
                lambda: bus.kv_watch("b", ">", lambda k, v: None),
                lambda: bus.request("orpheus/x", {}),
                lambda: bus.stream_publish("orpheus/x", {}),
                lambda: bus.stream_replay("s", lambda t, p: None),
            ):
                with pytest.raises(ConnectionError):
                    op()
        finally:
            bus.disconnect()


class TestConnectAbort:
    def test_timed_out_connect_does_not_leave_a_zombie_bus(self, monkeypatch) -> None:
        """connect()'s backstop timing out must abort the worker: the
        late-arriving connection is closed, no retry loop survives, and state is
        clean. Reaching the backstop means the worker is wedged in a way the
        per-attempt deadline can't unwind, so the factory blocks the loop."""
        fake = _FakeNats()

        async def _slow():
            time.sleep(0.6)  # blocking: wait_for cannot interrupt it
            return fake

        monkeypatch.setattr(event_bus_nats, "_CONNECT_UNWIND_GRACE", 0.05)
        bus = NatsBus(
            "nats://slow:4222",
            client_id="t",
            connect_coro_factory=_slow,
            connect_required=False,
            connect_timeout=0.1,
        )
        with pytest.raises(ConnectionError):
            bus.connect()
        assert bus._connect_abort is None  # the aborted worker's flag is not reusable
        assert bus._thread is None and bus._loop is None and bus._nc is None
        # Wait past the point the slow connect would have resolved: the
        # aborted worker must NOT attach it (no zombie bus, no retry loop).
        time.sleep(0.8)
        assert bus.is_connected is False and bus._nc is None
        # And the same instance can connect cleanly afterwards.
        bus._connect_coro_factory = _fast_factory(fake)
        bus.connect()
        try:
            assert bus.is_connected is True
        finally:
            bus.disconnect()

    def test_a_retry_cannot_un_abort_a_worker_that_is_still_connecting(
        self, monkeypatch
    ) -> None:
        """_teardown_thread joins with a bounded timeout and tolerates the join
        failing, so a disowned worker can still be inside its connect when a
        retry starts a new one. With one abort flag per BUS, connect()'s reset
        un-aborts it: when its connect finally resolves it reads "not aborted",
        publishes its connection over the live one and runs a loop nobody owns —
        the exact zombie the abort exists to prevent."""
        disowned = _FakeNats()
        replacement = _FakeNats()

        async def _blocked():
            # Blocks the loop, so the abort's loop.stop cannot unstick it: the
            # worker outlives the join and resolves successfully afterwards.
            time.sleep(0.5)
            return disowned

        monkeypatch.setattr(event_bus_nats, "_CONNECT_UNWIND_GRACE", 0.05)
        bus = NatsBus(
            "nats://slow:4222",
            client_id="t",
            connect_coro_factory=_blocked,
            connect_required=False,
            connect_timeout=0.1,
            op_timeout=0.05,  # the join gives up while the worker connects on
        )
        with pytest.raises(ConnectionError):
            bus.connect()

        # Retry while the first worker is still inside its connect.
        bus._connect_coro_factory = _fast_factory(replacement)
        bus.connect()
        try:
            assert bus._nc is replacement
            time.sleep(0.9)  # past the point the disowned connect resolves
            assert bus._nc is replacement, "the disowned worker attached over the live bus"
            assert disowned.closed is True, "the disowned connection was left open"
            assert bus.is_connected is True
        finally:
            bus.disconnect()


def _fast_factory(fake):
    async def _factory():
        return fake

    return _factory


class TestStreamReplayBrownout:
    def test_silent_broker_with_pending_messages_raises(self) -> None:
        """A fetch-timeout with messages still pending is a stalled replay,
        not a drain — it must raise, not report a partial count as complete."""
        js = type(
            "_Js",
            (),
            {
                "pull_subscribe": staticmethod(
                    lambda *a, **k: _async_return(_FakePullSub([], pending_after_drain=7))
                )
            },
        )()
        bus = _bus(_FakeNatsWithJs(js))
        bus.connect()
        try:
            with pytest.raises(ConnectionError):
                bus.stream_replay("s", lambda t, p: None)
        finally:
            bus.disconnect()


def _async_return(value):
    async def _coro(*a, **k):
        return value

    return _coro()


class TestKvWatchAttachOutcome:
    def test_absent_bucket_create_false_returns_false(self) -> None:
        """create=False on a bucket nobody created yet is NOT an attached watch
        — consumers gate their 'started' state on this return."""
        from nats.js.errors import NotFoundError

        class _Js:
            async def key_value(self, bucket):
                raise NotFoundError

        bus = _bus(_FakeNatsWithJs(_Js()))
        bus.connect()
        try:
            assert bus.kv_watch("nope", ">", lambda k, v: None, create=False) is False
        finally:
            bus.disconnect()
