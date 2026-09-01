"""Unit tests for the OperationalHealth KV façade (§11 health migration substrate).

Broker-free: exercised over a fake KV bus; the live KV behaviour is covered by the
JetStream live suite.
"""

from __future__ import annotations

from types import SimpleNamespace

from orpheus_common.actor import OperationalHealth
from orpheus_common.actor.operational_health import build_operational_health


class _FakeKvBus:
    def __init__(self, *, kv_supported: bool = True) -> None:
        self.kv_supported = kv_supported
        self.puts: list = []
        self.deletes: list = []
        self.watches: list = []
        self._store: dict[str, dict] = {}

    def _check(self) -> None:
        if not self.kv_supported:
            raise NotImplementedError("kv requires a JetStream backend")

    def kv_put(self, bucket, key, value, ttl=None):
        self._check()
        self.puts.append((bucket, key, value, ttl))
        self._store.setdefault(bucket, {})[key] = value
        return len(self.puts)

    def kv_delete(self, bucket, key):
        self._check()
        self.deletes.append((bucket, key))
        self._store.get(bucket, {}).pop(key, None)

    def kv_list(self, bucket):
        self._check()
        return dict(self._store.get(bucket, {}))

    def kv_watch(self, bucket, key_pattern, callback, *, create=True):
        self._check()
        self.watches.append((bucket, key_pattern, callback, create))


class TestOperationalHealth:
    def test_key_for_bare_name_and_instance(self):
        assert OperationalHealth.key_for("audio-events") == "audio-events"
        assert OperationalHealth.key_for("audio-motion", "host3-mic2") == "audio-motion__host3-mic2"

    def test_publish_writes_envelope_with_ttl(self):
        bus = _FakeKvBus()
        oh = OperationalHealth(bus, heartbeat_seconds=30.0)
        rev = oh.publish("audio-events", {"status": "online", "errors_count": 0})
        assert rev == 1
        bucket, key, value, ttl = bus.puts[0]
        assert (bucket, key) == ("orpheus_health", "audio-events")
        assert ttl == 90.0  # 3x heartbeat
        # payload preserved verbatim + additive envelope (superset, no shape change)
        assert value["status"] == "online"
        assert value["errors_count"] == 0
        assert value["agent"] == "audio-events"
        assert value["instance_id"] is None
        assert value["phase"] == "heartbeat"
        assert value["schema"] == 1
        assert "emitted_at" in value

    def test_publish_keys_by_bare_name_the_ui_expects(self):
        # The UI keys off "audio", not the client_id "orpheus-agent-audio-motion".
        bus = _FakeKvBus()
        OperationalHealth(bus).publish("audio", {"channels": []})
        assert bus.puts[0][1] == "audio"

    def test_instance_scoped_key(self):
        bus = _FakeKvBus()
        OperationalHealth(bus).publish(
            "audio-motion", {"x": 1}, instance_id="h3m2", phase="startup"
        )
        bucket, key, value, _ttl = bus.puts[0]
        assert key == "audio-motion__h3m2"
        assert value["instance_id"] == "h3m2"
        assert value["phase"] == "startup"

    def test_offline_deletes_key(self):
        bus = _FakeKvBus()
        oh = OperationalHealth(bus)
        oh.publish("crow-detection", {"status": "online"})
        oh.offline("crow-detection")
        assert bus.deletes == [("orpheus_health", "crow-detection")]
        assert oh.snapshot() == {}

    def test_snapshot_returns_all_producers(self):
        bus = _FakeKvBus()
        oh = OperationalHealth(bus)
        oh.publish("a", {"status": "online"})
        oh.publish("b", {"status": "online"})
        assert set(oh.snapshot()) == {"a", "b"}

    def test_watch_does_not_create_the_bucket(self):
        bus = _FakeKvBus()
        cb = lambda k, v: None  # noqa: E731
        OperationalHealth(bus, bucket="orpheus_health").watch(cb)
        assert bus.watches == [("orpheus_health", ">", cb, False)]  # create=False

    def test_explicit_ttl_overrides_heartbeat(self):
        bus = _FakeKvBus()
        oh = OperationalHealth(bus, ttl=120.0, heartbeat_seconds=30.0)
        assert oh.ttl == 120.0
        oh.publish("a", {})
        assert bus.puts[0][3] == 120.0

    def test_supported_true_on_kv_backend(self):
        assert OperationalHealth(_FakeKvBus(kv_supported=True)).supported() is True

    def test_supported_false_on_non_kv_backend(self):
        assert OperationalHealth(_FakeKvBus(kv_supported=False)).supported() is False


def _cfg(*, health_kv_enabled):
    return SimpleNamespace(event_bus=SimpleNamespace(health_kv_enabled=health_kv_enabled))


class TestBuildGate:
    """The shared gate is the reversibility guarantee: default OFF means every caller's
    dual-write is a no-op and the bus path is untouched. Pin each branch."""

    def test_none_when_bus_missing(self):
        assert build_operational_health(None, _cfg(health_kv_enabled=True)) is None

    def test_none_when_flag_off(self):
        # The default: flag off → no KV health, bus path unchanged.
        assert build_operational_health(_FakeKvBus(), _cfg(health_kv_enabled=False)) is None

    def test_none_when_config_has_no_event_bus(self):
        assert build_operational_health(_FakeKvBus(), SimpleNamespace()) is None

    def test_instance_when_enabled_and_kv_backend(self):
        oh = build_operational_health(_FakeKvBus(kv_supported=True), _cfg(health_kv_enabled=True))
        assert isinstance(oh, OperationalHealth)

    def test_none_when_enabled_but_backend_lacks_kv(self):
        # Flag on but mqtt/non-KV backend → still None (can't publish; falls back to bus).
        assert build_operational_health(
            _FakeKvBus(kv_supported=False), _cfg(health_kv_enabled=True)
        ) is None

    def test_ttl_is_fleet_derived_not_per_agent(self):
        # Shared bucket + first-creator-wins ttl: the gate derives the ttl from
        # the fleet's slowest configured heartbeat, NOT the calling agent's
        # (a slow-tick agent would otherwise flap out of a fast agent's bucket).
        cfg = SimpleNamespace(
            event_bus=SimpleNamespace(health_kv_enabled=True),
            agents={"slow": SimpleNamespace(heartbeat_seconds=120.0)},
        )
        oh = build_operational_health(_FakeKvBus(), cfg, heartbeat_seconds=5.0)
        assert oh is not None
        assert oh.ttl == 360.0  # 3x the largest heartbeat, not 3x5s

    def test_explicit_health_ttl_seconds_override(self):
        # The named config seam: event_bus.health_ttl_seconds wins when present.
        cfg = SimpleNamespace(
            event_bus=SimpleNamespace(health_kv_enabled=True, health_ttl_seconds=45.0)
        )
        oh = build_operational_health(_FakeKvBus(), cfg)
        assert oh is not None and oh.ttl == 45.0
