"""Tests for ``JetStreamKvConfigBackend`` — the KV-distributed config override
layer (ADR 0018). Unit tests run over a fake KV bus; the live distribution
roundtrip runs against nats-server and skips otherwise.
"""

from __future__ import annotations

import uuid

import pytest

from orpheus_common.config_backend import (
    MISSING,
    ConfigBackend,
    JetStreamKvConfigBackend,
)
from orpheus_common.config_store import ConfigStore

NATS_URL = "nats://127.0.0.1:4222"


class _FakeKvBus:
    """In-memory KV honoring the EventBus contract: kv_get returns None ONLY when
    the key is absent (a stored envelope dict is never None)."""

    def __init__(self) -> None:
        self.kv: dict = {}

    def kv_get(self, bucket, key):
        return self.kv.get(bucket, {}).get(key)

    def kv_put(self, bucket, key, value, ttl=None):
        self.kv.setdefault(bucket, {})[key] = value
        return len(self.kv[bucket])


class TestKvConfigBackendUnit:
    def test_current_missing_when_absent(self):
        be = JetStreamKvConfigBackend(_FakeKvBus())
        assert be.current("audio.gain") is MISSING

    def test_put_then_current_roundtrip(self):
        be = JetStreamKvConfigBackend(_FakeKvBus())
        assert be.put("audio.gain", {"x": 1}, "me", "2026-01-01T00:00:00Z") == 1
        assert be.current("audio.gain") == {"x": 1}

    def test_put_bumps_version_monotonically(self):
        be = JetStreamKvConfigBackend(_FakeKvBus())
        assert be.put("k", "a", "me", "t") == 1
        assert be.put("k", "b", "me", "t") == 2
        assert be.current("k") == "b"

    def test_stored_none_is_honoured_not_missing(self):
        be = JetStreamKvConfigBackend(_FakeKvBus())
        be.put("k", None, "me", "t")
        assert be.current("k") is None  # explicit None, distinct from MISSING

    def test_history_exposes_current_version_only(self):
        be = JetStreamKvConfigBackend(_FakeKvBus())
        assert be.history("k", 10) == []  # absent -> empty
        be.put("k", "a", "alice", "2026-01-01T00:00:00Z")
        be.put("k", "b", "bob", "2026-01-02T00:00:00Z")
        hist = be.history("k", 10)
        assert len(hist) == 1  # KV keeps no trail; SQLite is the audit-of-record
        assert (hist[0].value, hist[0].version, hist[0].author) == ("b", 2, "bob")

    def test_satisfies_configbackend_protocol(self):
        assert isinstance(JetStreamKvConfigBackend(_FakeKvBus()), ConfigBackend)

    def test_distribution_one_writer_many_readers(self):
        # ONE authority writes; a SEPARATE store/backend over the same KV reads it
        # (the cross-host "hosts don't copy identical YAML" case, over a fake KV).
        bus = _FakeKvBus()
        authority = ConfigStore(
            backend=JetStreamKvConfigBackend(bus), yaml_getter=lambda k: MISSING
        )
        reader = ConfigStore(
            backend=JetStreamKvConfigBackend(bus), yaml_getter=lambda k: MISSING
        )
        authority.set("audio.gain", 0.7, author="authority")
        assert reader.get("audio.gain", env_override=False) == 0.7


@pytest.fixture
def live_bus():
    from orpheus_common.event_bus_nats import NatsBus

    bus = NatsBus(NATS_URL, client_id="cfgkv", connect_timeout=2.0)
    try:
        bus.connect()
    except Exception:
        pytest.skip(f"no nats-server on {NATS_URL}")
    yield bus
    bus.disconnect()


class TestKvConfigBackendLive:
    def test_distribution_roundtrip_live(self, live_bus):
        bucket = "cfg-" + uuid.uuid4().hex[:8]
        store = ConfigStore(
            backend=JetStreamKvConfigBackend(live_bus, bucket=bucket),
            yaml_getter=lambda k: MISSING,
        )
        store.set("audio.gain", 0.7, author="authority")
        assert store.get("audio.gain", env_override=False) == 0.7
        assert store.history("audio.gain")[0].version == 1

        # A fresh backend over the same bucket (== another host) reads the value.
        reader = JetStreamKvConfigBackend(live_bus, bucket=bucket)
        assert reader.current("audio.gain") == 0.7

        # A second write bumps the version + is visible to the reader.
        store.set("audio.gain", 0.9, author="authority")
        assert reader.current("audio.gain") == 0.9
        assert store.history("audio.gain")[0].version == 2
