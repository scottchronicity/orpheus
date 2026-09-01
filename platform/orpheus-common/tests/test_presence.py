"""Unit tests for the KV-TTL Presence helper + the retain subject-matcher.

Broker-free: Presence is exercised over a fake bus that records kv_* calls; the
live KV-TTL/expiry behaviour is in test_event_bus_jetstream.py (needs nats-server).
"""

from __future__ import annotations

import pytest

from orpheus_common.actor import Presence
from orpheus_common.event_bus_nats import _subject_matches


class _FakeKvBus:
    """Records kv_* calls; an in-memory store backs kv_list/kv_put/kv_delete."""

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


class TestPresence:
    def test_online_writes_ttld_key_with_default_payload(self):
        bus = _FakeKvBus()
        pres = Presence(bus, bucket="pres", heartbeat_seconds=30.0)
        rev = pres.online("agent-a")
        assert rev == 1
        bucket, key, value, ttl = bus.puts[0]
        assert (bucket, key, value) == ("pres", "agent-a", {"status": "online"})
        assert ttl == 90.0  # 3x heartbeat default

    def test_explicit_ttl_overrides_heartbeat_default(self):
        bus = _FakeKvBus()
        pres = Presence(bus, ttl=5.0, heartbeat_seconds=30.0)
        assert pres.ttl == 5.0
        pres.online("a")
        assert bus.puts[0][3] == 5.0

    def test_online_custom_payload(self):
        bus = _FakeKvBus()
        Presence(bus, bucket="pres").online("a", {"host": "nuc-1"})
        assert bus.puts[0][2] == {"host": "nuc-1"}

    def test_offline_deletes_key(self):
        bus = _FakeKvBus()
        pres = Presence(bus, bucket="pres")
        pres.online("a")
        pres.offline("a")
        assert bus.deletes == [("pres", "a")]
        assert pres.snapshot() == {}

    def test_snapshot_lists_live_agents(self):
        bus = _FakeKvBus()
        pres = Presence(bus, bucket="pres")
        pres.online("a", {"status": "online"})
        pres.online("b", {"status": "online"})
        assert pres.snapshot() == {
            "a": {"status": "online"},
            "b": {"status": "online"},
        }

    def test_watch_registers_full_bucket_pattern(self):
        bus = _FakeKvBus()
        cb = lambda k, v: None  # noqa: E731
        Presence(bus, bucket="pres").watch(cb)
        assert bus.watches == [("pres", ">", cb, False)]

    def test_watch_never_creates_the_bucket(self):
        # A consumer watching BEFORE any producer wrote must not create the
        # bucket: NATS KV ttl is bucket-wide + fixed at create, so a
        # watcher-created bucket would have NO ttl and presence keys would
        # never expire (kill -9'd agents online forever). create=False, like
        # OperationalHealth.watch.
        bus = _FakeKvBus()
        Presence(bus, bucket="pres").watch(lambda k, v: None)
        assert bus.watches[0][3] is False  # create flag

    def test_supported_true_on_kv_backend(self):
        assert Presence(_FakeKvBus(kv_supported=True)).supported() is True

    def test_supported_false_on_non_kv_backend(self):
        assert Presence(_FakeKvBus(kv_supported=False)).supported() is False

    def test_supported_true_when_transport_is_down(self):
        # A cold/unattached broker raises ConnectionError from the KV surface;
        # that is "transport down", NOT "backend has no KV" — supported() must
        # stay True so the consumer wires up and works once the broker attaches.
        class _ColdBus(_FakeKvBus):
            def kv_list(self, bucket):
                raise ConnectionError("not attached yet")

        assert Presence(_ColdBus()).supported() is True


class TestFleetTtlSeconds:
    """fleet_ttl_seconds — the shared-bucket ttl every agent derives from the SAME
    yaml, decoupled from its own heartbeat. NATS KV ttl is bucket-wide + first-
    creator-wins, so a per-agent 3x-heartbeat derivation flaps any agent slower
    than the bucket's creator (per-agent ticks via agents.<name>.heartbeat_seconds)."""

    def test_default_is_3x_default_heartbeat(self):
        from types import SimpleNamespace

        from orpheus_common.actor.kv_ttl_bucket import fleet_ttl_seconds

        assert fleet_ttl_seconds(SimpleNamespace(), "presence_ttl_seconds") == 90.0

    def test_sized_to_largest_configured_heartbeat(self):
        # agents: {fast: 5s, slow: 120s} → every agent requests 3x120, so the
        # slow agent never outlives its key whoever creates the bucket.
        from types import SimpleNamespace

        from orpheus_common.actor.kv_ttl_bucket import fleet_ttl_seconds

        cfg = SimpleNamespace(
            agents={
                "audio-motion": SimpleNamespace(heartbeat_seconds=5.0),
                "event-correlator": SimpleNamespace(heartbeat_seconds=120.0),
            }
        )
        assert fleet_ttl_seconds(cfg, "presence_ttl_seconds") == 360.0

    def test_floored_at_default_heartbeat(self):
        # All-fast fleets keep today's 90s window (never shrink below 3x30s).
        from types import SimpleNamespace

        from orpheus_common.actor.kv_ttl_bucket import fleet_ttl_seconds

        cfg = SimpleNamespace(agents={"a": SimpleNamespace(heartbeat_seconds=5.0)})
        assert fleet_ttl_seconds(cfg, "presence_ttl_seconds") == 90.0

    def test_explicit_override_key_wins(self):
        # The named seam for the config owner: event_bus.presence_ttl_seconds /
        # health_ttl_seconds, read via getattr (inert until the field exists).
        from types import SimpleNamespace

        from orpheus_common.actor.kv_ttl_bucket import fleet_ttl_seconds

        cfg = SimpleNamespace(
            event_bus=SimpleNamespace(presence_ttl_seconds=42.0),
            agents={"slow": SimpleNamespace(heartbeat_seconds=600.0)},
        )
        assert fleet_ttl_seconds(cfg, "presence_ttl_seconds") == 42.0

    def test_mock_config_cannot_leak_into_ttl_math(self):
        # Strict coercion: a Mock's auto-attributes are ignored, not multiplied.
        from unittest.mock import Mock

        from orpheus_common.actor.kv_ttl_bucket import fleet_ttl_seconds

        assert fleet_ttl_seconds(Mock(), "presence_ttl_seconds") == 90.0


class TestSubjectMatches:
    @pytest.mark.parametrize(
        "pattern,subject,expected",
        [
            ("a.b.c", "a.b.c", True),
            ("a.b.c", "a.b.d", False),
            ("a.b", "a.b.c", False),  # length mismatch (too short)
            ("a.b.c", "a.b", False),  # length mismatch (too long)
            ("a.*.c", "a.b.c", True),  # single-token wildcard
            ("a.*.c", "a.b.d", False),
            ("a.>", "a.b.c", True),  # tail wildcard, multi token
            ("a.>", "a.b", True),
            ("a.>", "a", False),  # ``>`` requires at least one trailing token
            ("orpheus.state.+", "orpheus.state.x", False),  # ``+`` is mqtt, not nats
        ],
    )
    def test_match(self, pattern, subject, expected):
        assert _subject_matches(pattern, subject) is expected
