"""Tests for ``orpheus-config push`` — flatten + push the canonical config into the
backplane KV (ADR 0018). The bus glue in ``main()`` is thin; the pure pieces
(flatten + push_config over a KV-backed store) are unit-tested here.
"""

from __future__ import annotations

from orpheus_common.config_backend import MISSING, JetStreamKvConfigBackend
from orpheus_common.config_push import (
    flatten_config,
    push_config,
    strip_bootstrap_local,
)
from orpheus_common.config_store import ConfigStore


class _FakeKvBus:
    def __init__(self) -> None:
        self.kv: dict = {}
        self.published: list = []

    def kv_get(self, bucket, key):
        return self.kv.get(bucket, {}).get(key)

    def kv_put(self, bucket, key, value, ttl=None):
        self.kv.setdefault(bucket, {})[key] = value
        return len(self.kv[bucket])

    def publish(self, topic, payload):
        self.published.append((topic, payload))


class TestFlattenConfig:
    def test_flattens_nested_dicts_to_dotted_leaves(self):
        flat = flatten_config({"audio": {"gain": 0.5, "device": {"name": "mic"}}, "x": 1})
        assert flat == {"audio.gain": 0.5, "audio.device.name": "mic", "x": 1}

    def test_lists_and_scalars_are_leaves(self):
        flat = flatten_config({"topics": ["a", "b"], "n": 3, "flag": True})
        assert flat == {"topics": ["a", "b"], "n": 3, "flag": True}

    def test_empty_and_none_safe(self):
        assert flatten_config({}) == {}
        assert flatten_config(None) == {}


class TestStripBootstrapLocal:
    def test_drops_event_bus_and_config_service_keeps_rest(self):
        flat = {
            "audio.gain": 0.5,
            "event_bus.nats_url": "nats://x",
            "event_bus.backend": "nats",
            "config_service.enabled": True,
            "mqtt.broker_host": "h",
        }
        assert strip_bootstrap_local(flat) == {"audio.gain": 0.5, "mqtt.broker_host": "h"}

    def test_no_bootstrap_keys_is_unchanged(self):
        flat = {"audio.gain": 0.5, "mqtt.broker_host": "h"}
        assert strip_bootstrap_local(flat) == flat


class TestPushConfig:
    def test_pushes_every_leaf_into_the_backend(self):
        bus = _FakeKvBus()
        store = ConfigStore(
            backend=JetStreamKvConfigBackend(bus), yaml_getter=lambda _k: MISSING, bus=bus
        )
        flat = {"audio.gain": 0.5, "mqtt.broker_host": "localhost"}
        assert push_config(flat, store, author="authority") == 2
        # A reader over the same KV resolves the pushed values.
        assert store.get("audio.gain", env_override=False) == 0.5
        assert store.get("mqtt.broker_host", env_override=False) == "localhost"

    def test_push_records_author_in_history(self):
        bus = _FakeKvBus()
        store = ConfigStore(
            backend=JetStreamKvConfigBackend(bus), yaml_getter=lambda _k: MISSING
        )
        push_config({"audio.gain": 0.5}, store, author="deploy-bot")
        hist = store.history("audio.gain")
        assert hist[0].author == "deploy-bot"
        assert hist[0].value == 0.5
