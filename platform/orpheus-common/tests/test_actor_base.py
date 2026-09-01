"""Tests for the thin Actor base lifecycle (setup → connect/subscribe → startup
health → heartbeat → graceful shutdown), driven on a ManualClock."""

import asyncio
from types import SimpleNamespace

from orpheus_common.actor import ManualClock
from orpheus_common.actor import base as actor_base


async def _settle(n: int = 3) -> None:
    for _ in range(n):
        await asyncio.sleep(0)


class _FakeBus:
    def __init__(self) -> None:
        self.connected = False
        self.disconnected = False
        self.subs: list = []
        self.published: list = []
        self.kv: dict = {}  # bucket -> {key: value} (presence-capable fake)

    @property
    def is_connected(self) -> bool:
        return self.connected and not self.disconnected

    def subscribe(self, topic, cb) -> None:
        self.subs.append(topic)

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.disconnected = True

    def publish(self, topic, payload) -> None:
        self.published.append((topic, payload))

    def kv_put(self, bucket, key, value, ttl=None) -> int:
        self.kv.setdefault(bucket, {})[key] = value
        return len(self.kv[bucket])

    def kv_delete(self, bucket, key) -> None:
        self.kv.get(bucket, {}).pop(key, None)

    def kv_list(self, bucket) -> dict:
        return dict(self.kv.get(bucket, {}))


class _FakeActor(actor_base.Actor):
    def __init__(self, *a, **k) -> None:
        super().__init__(*a, **k)
        self.setup_called = False
        self.shutdown_called = False

    async def on_setup(self) -> None:
        self.setup_called = True

    def subscriptions(self):
        return [
            ("orpheus/detection/bird/events", lambda t, p: None),
            ("orpheus/detection/audio/events", lambda t, p: None),
        ]

    def health_payload(self, phase):
        status = "offline" if phase == "shutdown" else "online"
        return {"status": status, "phase": phase}

    async def on_shutdown(self) -> None:
        self.shutdown_called = True


HEALTH = "orpheus/system/crow-detection/health"


def test_actor_full_lifecycle(monkeypatch):
    async def scenario():
        bus = _FakeBus()
        # The base builds the bus + installs real OS signal handlers; stub both so
        # the test drives a fake bus and doesn't touch process signals.
        monkeypatch.setattr(actor_base, "create_event_bus", lambda *a, **k: bus)
        monkeypatch.setattr(actor_base, "install_signal_handlers", lambda *a, **k: None)

        clock = ManualClock()
        actor = _FakeActor("crow-detection", object(), clock=clock, heartbeat_seconds=30.0)
        task = asyncio.ensure_future(actor.start())
        await _settle()

        # setup ran; bus connected; both topics subscribed; identity-derived client.
        assert actor.setup_called
        assert bus.connected
        assert bus.subs == [
            "orpheus/detection/bird/events",
            "orpheus/detection/audio/events",
        ]
        assert actor.identity.client_id == "orpheus-agent-crow-detection"

        # startup health published immediately.
        assert bus.published[0] == (HEALTH, {"status": "online", "phase": "startup"})

        # heartbeat fires on each interval (deterministic via ManualClock).
        clock.advance(30)
        await _settle()
        assert bus.published[-1] == (HEALTH, {"status": "online", "phase": "heartbeat"})

        # graceful shutdown: offline health, disconnect, teardown hook.
        actor.stop_event.set()
        await _settle()
        await task
        assert bus.published[-1] == (HEALTH, {"status": "offline", "phase": "shutdown"})
        assert bus.disconnected
        assert actor.shutdown_called
        return True

    assert asyncio.run(scenario()) is True


def test_started_and_stopping_hook_ordering(monkeypatch):
    async def scenario():
        bus = _FakeBus()
        monkeypatch.setattr(actor_base, "create_event_bus", lambda *a, **k: bus)
        monkeypatch.setattr(actor_base, "install_signal_handlers", lambda *a, **k: None)
        seen = []

        class _Hooked(_FakeActor):
            async def on_started(self) -> None:
                seen.append(("started", bus.connected, bus.disconnected))

            async def on_stopping(self) -> None:
                seen.append(("stopping", bus.connected, bus.disconnected))

        actor = _Hooked("crow-detection", object())
        task = asyncio.ensure_future(actor.start())
        await _settle()
        actor.stop_event.set()
        await _settle()
        await task
        return seen

    seen = asyncio.run(scenario())
    # on_started runs after connect; on_stopping runs while STILL connected (before
    # disconnect) so it can publish — both with the bus up, not disconnected.
    assert ("started", True, False) in seen
    assert ("stopping", True, False) in seen


def test_actor_disabled_does_not_start(monkeypatch):
    async def scenario():
        bus = _FakeBus()
        monkeypatch.setattr(actor_base, "create_event_bus", lambda *a, **k: bus)
        monkeypatch.setattr(actor_base, "install_signal_handlers", lambda *a, **k: None)

        class _Disabled(_FakeActor):
            def enabled(self) -> bool:
                return False

        actor = _Disabled("crow-detection", object())
        await actor.start()  # returns immediately, no bus
        return bus.connected, actor.setup_called

    connected, setup_called = asyncio.run(scenario())
    assert connected is False
    assert setup_called is False


def test_instance_id_read_from_deploy_env(monkeypatch):
    # ORPHEUS_AGENT_INSTANCE_ID -> unique identity, no per-agent code (deploy seam).
    monkeypatch.setenv("ORPHEUS_AGENT_INSTANCE_ID", "host3-mic2")
    actor = actor_base.Actor("audio-motion", object())
    assert actor.identity.instance_id == "host3-mic2"
    assert actor.identity.client_id == "orpheus-agent-audio-motion-host3-mic2"
    assert actor.identity.health_topic == "orpheus/system/audio-motion/host3-mic2/health"


def test_explicit_instance_id_overrides_env(monkeypatch):
    monkeypatch.setenv("ORPHEUS_AGENT_INSTANCE_ID", "from-env")
    actor = actor_base.Actor("audio-motion", object(), instance_id="explicit")
    assert actor.identity.instance_id == "explicit"


_PRESENCE_BUCKET = "orpheus_presence"


def test_presence_off_by_default(monkeypatch):
    # No event_bus.presence_enabled ⇒ nothing written to the presence bucket.
    async def scenario():
        bus = _FakeBus()
        monkeypatch.setattr(actor_base, "create_event_bus", lambda *a, **k: bus)
        monkeypatch.setattr(actor_base, "install_signal_handlers", lambda *a, **k: None)
        actor = _FakeActor("crow-detection", object())
        task = asyncio.ensure_future(actor.start())
        await _settle()
        actor.stop_event.set()
        await _settle()
        await task
        return bus.kv_list(_PRESENCE_BUCKET)

    assert asyncio.run(scenario()) == {}


def test_presence_emitted_when_enabled(monkeypatch):
    # event_bus.presence_enabled + a KV-capable backend ⇒ online at startup, refresh
    # on each heartbeat, offline (key deleted) on graceful shutdown.
    async def scenario():
        bus = _FakeBus()
        monkeypatch.setattr(actor_base, "create_event_bus", lambda *a, **k: bus)
        monkeypatch.setattr(actor_base, "install_signal_handlers", lambda *a, **k: None)
        cfg = SimpleNamespace(event_bus=SimpleNamespace(presence_enabled=True))
        clock = ManualClock()
        actor = _FakeActor("crow-detection", cfg, clock=clock, heartbeat_seconds=30.0)
        task = asyncio.ensure_future(actor.start())
        await _settle()
        cid = "orpheus-agent-crow-detection"

        online_at_startup = cid in bus.kv_list(_PRESENCE_BUCKET)
        clock.advance(30)
        await _settle()
        present_after_heartbeat = cid in bus.kv_list(_PRESENCE_BUCKET)

        actor.stop_event.set()
        await _settle()
        await task
        offline_after_shutdown = cid not in bus.kv_list(_PRESENCE_BUCKET)
        return online_at_startup, present_after_heartbeat, offline_after_shutdown

    assert asyncio.run(scenario()) == (True, True, True)


def test_presence_ttl_is_fleet_derived_not_per_agent(monkeypatch):
    # The presence bucket is SHARED and its ttl is fixed by the first creator, so
    # the ttl each agent requests must come from the fleet's slowest configured
    # heartbeat — NOT 3x this agent's own (a 120s-tick agent joining a 90s bucket
    # would expire between its own beats and flap offline forever).
    bus = _FakeBus()
    cfg = SimpleNamespace(
        event_bus=SimpleNamespace(presence_enabled=True),
        agents={
            "crow-detection": SimpleNamespace(heartbeat_seconds=5.0),
            "event-correlator": SimpleNamespace(heartbeat_seconds=120.0),
        },
    )
    actor = _FakeActor("crow-detection", cfg, heartbeat_seconds=5.0)
    actor.bus = bus
    presence = actor._make_presence()
    assert presence is not None
    assert presence.ttl == 360.0  # 3x the LARGEST configured heartbeat, not 3x5s


_HEALTH_BUCKET = "orpheus_health"


def test_health_kv_dual_write_off_by_default(monkeypatch):
    # No event_bus.health_kv_enabled ⇒ nothing written to orpheus_health; the bus
    # health publish is unaffected (still on the health topic).
    async def scenario():
        bus = _FakeBus()
        monkeypatch.setattr(actor_base, "create_event_bus", lambda *a, **k: bus)
        monkeypatch.setattr(actor_base, "install_signal_handlers", lambda *a, **k: None)
        actor = _FakeActor("crow-detection", object())
        task = asyncio.ensure_future(actor.start())
        await _settle()
        actor.stop_event.set()
        await _settle()
        await task
        # bus health still published (startup at least); KV untouched.
        return bus.kv_list(_HEALTH_BUCKET), any(t == HEALTH for t, _ in bus.published)

    kv, bus_health = asyncio.run(scenario())
    assert kv == {}
    assert bus_health is True  # bus path byte-identical (dual-write is additive)


def test_health_kv_dual_write_when_enabled(monkeypatch):
    # health_kv_enabled + KV backend ⇒ health dual-written under the BARE agent name,
    # in addition to the bus publish; offline (delete) on graceful shutdown.
    async def scenario():
        bus = _FakeBus()
        monkeypatch.setattr(actor_base, "create_event_bus", lambda *a, **k: bus)
        monkeypatch.setattr(actor_base, "install_signal_handlers", lambda *a, **k: None)
        cfg = SimpleNamespace(event_bus=SimpleNamespace(health_kv_enabled=True))
        clock = ManualClock()
        actor = _FakeActor("crow-detection", cfg, clock=clock, heartbeat_seconds=30.0)
        task = asyncio.ensure_future(actor.start())
        await _settle()
        # Keyed by the bare agent name (what the UI expects), not the client_id.
        present_at_startup = "crow-detection" in bus.kv_list(_HEALTH_BUCKET)
        envelope = bus.kv_list(_HEALTH_BUCKET).get("crow-detection", {})
        bus_still_published = any(t == HEALTH for t, _ in bus.published)
        clock.advance(30)
        await _settle()
        present_after_heartbeat = "crow-detection" in bus.kv_list(_HEALTH_BUCKET)
        actor.stop_event.set()
        await _settle()
        await task
        offline_after_shutdown = "crow-detection" not in bus.kv_list(_HEALTH_BUCKET)
        return (
            present_at_startup,
            envelope.get("agent"),
            envelope.get("status"),  # health_payload superset preserved
            bus_still_published,
            present_after_heartbeat,
            offline_after_shutdown,
        )

    result = asyncio.run(scenario())
    assert result == (True, "crow-detection", "online", True, True, True)


def test_health_on_bus_false_suppresses_bus_publish_when_kv_active(monkeypatch):
    # §11 Phase 5a: health_on_bus=false + KV active ⇒ no bus health publishes, but the
    # heartbeat still ticks (KV health written) — health served from KV only.
    async def scenario():
        bus = _FakeBus()
        monkeypatch.setattr(actor_base, "create_event_bus", lambda *a, **k: bus)
        monkeypatch.setattr(actor_base, "install_signal_handlers", lambda *a, **k: None)
        cfg = SimpleNamespace(
            event_bus=SimpleNamespace(health_on_bus=False, health_kv_enabled=True)
        )
        clock = ManualClock()
        actor = _FakeActor("crow-detection", cfg, clock=clock, heartbeat_seconds=30.0)
        task = asyncio.ensure_future(actor.start())
        await _settle()
        clock.advance(30)
        await _settle()
        actor.stop_event.set()
        await _settle()
        await task
        # The bus never carried health (suppressed); KV carried it (op_health wrote
        # at startup/heartbeat, then offline-deleted on shutdown).
        return any(t == HEALTH for t, _ in bus.published)

    assert asyncio.run(scenario()) is False  # bus health fully suppressed


def test_health_on_bus_false_kept_when_kv_inactive(monkeypatch):
    # Anti-skew guard: health_on_bus=false but KV NOT active ⇒ keep the bus publish
    # (never leave the UI with no health source).
    async def scenario():
        bus = _FakeBus()
        monkeypatch.setattr(actor_base, "create_event_bus", lambda *a, **k: bus)
        monkeypatch.setattr(actor_base, "install_signal_handlers", lambda *a, **k: None)
        cfg = SimpleNamespace(event_bus=SimpleNamespace(health_on_bus=False))  # no KV
        actor = _FakeActor("crow-detection", cfg)
        task = asyncio.ensure_future(actor.start())
        await _settle()
        actor.stop_event.set()
        await _settle()
        await task
        return any(t == HEALTH for t, _ in bus.published)

    assert asyncio.run(scenario()) is True  # bus health kept (safety)


def test_no_instance_env_is_single_instance(monkeypatch):
    monkeypatch.delenv("ORPHEUS_AGENT_INSTANCE_ID", raising=False)
    actor = actor_base.Actor("audio-motion", object())
    assert actor.identity.instance_id is None
    assert actor.identity.client_id == "orpheus-agent-audio-motion"


class TestConfigDrivenTickFrequency:
    """agents.<name>.heartbeat_seconds resolution: explicit constructor arg >
    config > the 30s default. Strict coercion so mocked configs can't leak
    into the timer math."""

    def test_default_is_30s(self):
        from orpheus_common.config import OrpheusConfig

        cfg = OrpheusConfig.from_dict({"mqtt": {"broker_host": "h"}}, source="<test>")
        agent = _FakeActor("crow-detection", cfg)
        assert agent.heartbeat_seconds == 30.0

    def test_config_drives_per_agent_frequency(self):
        from orpheus_common.config import OrpheusConfig

        cfg = OrpheusConfig.from_dict(
            {
                "mqtt": {"broker_host": "h"},
                "agents": {
                    "crow-detection": {"heartbeat_seconds": 5.0},
                    "event-correlator": {"heartbeat_seconds": 120.0},
                },
            },
            source="<test>",
        )
        assert _FakeActor("crow-detection", cfg).heartbeat_seconds == 5.0
        assert _FakeActor("event-correlator", cfg).heartbeat_seconds == 120.0
        assert _FakeActor("bird-detection", cfg).heartbeat_seconds == 30.0  # unconfigured

    def test_explicit_arg_beats_config(self):
        from orpheus_common.config import OrpheusConfig

        cfg = OrpheusConfig.from_dict(
            {
                "mqtt": {"broker_host": "h"},
                "agents": {"crow-detection": {"heartbeat_seconds": 5.0}},
            },
            source="<test>",
        )
        agent = _FakeActor("crow-detection", cfg, heartbeat_seconds=1.5)
        assert agent.heartbeat_seconds == 1.5

    def test_mock_config_falls_back_to_default(self):
        from unittest.mock import Mock

        agent = _FakeActor("crow-detection", Mock())
        assert agent.heartbeat_seconds == 30.0

    def test_invalid_heartbeat_raises_config_error(self):
        import pytest

        from orpheus_common.config import ConfigError, OrpheusConfig

        with pytest.raises(ConfigError, match="heartbeat_seconds must be > 0"):
            OrpheusConfig.from_dict(
                {"mqtt": {"broker_host": "h"}, "agents": {"x": {"heartbeat_seconds": 0}}},
                source="<test>",
            )
