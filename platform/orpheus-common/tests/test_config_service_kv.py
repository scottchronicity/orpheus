"""Tests for the ADR-0018 config-service KV layer in ``OrpheusConfig`` — the base
config distributed over the backplane KV, merged OVER local YAML (env still wins),
off by default. Unit tests inject a fake NatsBus; the live test uses nats-server.
"""

from __future__ import annotations

import uuid

import pytest

from orpheus_common.config import (
    OrpheusConfig,
    _deep_merge_config,
    _unflatten_dotted,
)


class _FakeNatsBus:
    """Stands in for NatsBus: kv_list returns JetStream-KV envelopes (the shape
    JetStreamKvConfigBackend writes)."""

    LISTED = {
        "mqtt.broker_host": {"value": "kvhost", "version": 1},
        "site.name": {"value": "KV Site", "version": 1},
    }

    def __init__(self, url, *, client_id=None, connect_timeout=None, **kwargs):
        self.url = url

    def connect(self):
        pass

    def disconnect(self):
        pass

    def kv_list(self, bucket):
        return dict(self.LISTED)


class TestUnflattenAndMerge:
    def test_unflatten_dotted_rebuilds_tree(self):
        assert _unflatten_dotted({"a.b": 1, "a.c": 2, "x": 3}) == {
            "a": {"b": 1, "c": 2},
            "x": 3,
        }

    def test_unflatten_leaf_never_clobbers_a_built_subtree(self):
        # A malformed KV carrying both "a.b.c" and a bare "a.b" leaf must not
        # let the leaf silently drop the subtree (log-and-skip instead).
        assert _unflatten_dotted({"a.b.c": 1, "a.b": 2}) == {"a": {"b": {"c": 1}}}

    def test_unflatten_subtree_after_leaf_is_skipped(self):
        # The mirror-image collision (leaf first) was already handled; keep it.
        assert _unflatten_dotted({"a.b": 2, "a.b.c": 1}) == {"a": {"b": 2}}

    def test_deep_merge_override_wins_and_inputs_unmutated(self):
        base = {"a": {"b": 1, "c": 2}, "x": 1}
        override = {"a": {"c": 9, "d": 3}, "y": 2}
        assert _deep_merge_config(base, override) == {
            "a": {"b": 1, "c": 9, "d": 3},
            "x": 1,
            "y": 2,
        }
        assert base == {"a": {"b": 1, "c": 2}, "x": 1}  # not mutated


class TestConfigServiceKvLayer:
    def test_off_by_default_never_touches_the_bus(self, monkeypatch):
        calls = {"n": 0}

        class _Boom:
            def __init__(self, *a, **k):
                calls["n"] += 1

        monkeypatch.setattr("orpheus_common.event_bus_nats.NatsBus", _Boom)
        cfg = OrpheusConfig.from_dict({"mqtt": {"broker_host": "localhost"}}, source="<t>")
        assert cfg.mqtt.broker_host == "localhost"
        assert calls["n"] == 0  # no config_service section -> no KV read

    def test_kv_merges_over_local_when_enabled(self, monkeypatch):
        monkeypatch.setattr("orpheus_common.event_bus_nats.NatsBus", _FakeNatsBus)
        cfg = OrpheusConfig.from_dict(
            {
                "mqtt": {"broker_host": "localhost"},
                "event_bus": {"backend": "nats", "nats_url": "nats://x:4222"},
                "config_service": {"enabled": True},
            },
            source="<t>",
        )
        assert cfg.mqtt.broker_host == "kvhost"  # KV wins over local YAML
        assert cfg.site.name == "KV Site"  # KV-only value applied

    def test_env_wins_over_kv(self, monkeypatch):
        monkeypatch.setattr("orpheus_common.event_bus_nats.NatsBus", _FakeNatsBus)
        monkeypatch.setenv("ORPHEUS_MQTT__BROKER_HOST", "envhost")
        cfg = OrpheusConfig.from_dict(
            {
                "mqtt": {"broker_host": "localhost"},
                "event_bus": {"backend": "nats"},
                "config_service": {"enabled": True},
            },
            source="<t>",
        )
        assert cfg.mqtt.broker_host == "envhost"  # env applied after the KV merge

    def test_broker_unreachable_falls_back_to_local(self, monkeypatch):
        class _ColdBus:
            def __init__(self, *a, **k):
                pass

            def connect(self):
                raise ConnectionError("broker cold")

            def disconnect(self):
                pass

        monkeypatch.setattr("orpheus_common.event_bus_nats.NatsBus", _ColdBus)
        cfg = OrpheusConfig.from_dict(
            {
                "mqtt": {"broker_host": "localhost"},
                "event_bus": {"backend": "nats"},
                "config_service": {"enabled": True},
            },
            source="<t>",
        )
        assert cfg.mqtt.broker_host == "localhost"  # fell back, did not raise

    def test_kv_entry_without_value_never_merges_none_over_local(self, monkeypatch):
        class _SparseBus(_FakeNatsBus):
            LISTED = {
                "mqtt.broker_host": {"version": 1},  # no "value" key at all
                "site.name": {"value": None, "version": 1},  # explicit null
                "site.elevation": {"value": 12.0, "version": 1},  # real value
            }

        monkeypatch.setattr("orpheus_common.event_bus_nats.NatsBus", _SparseBus)
        cfg = OrpheusConfig.from_dict(
            {
                "mqtt": {"broker_host": "localhost"},
                "site": {"name": "Local Site"},
                "event_bus": {"backend": "nats"},
                "config_service": {"enabled": True},
            },
            source="<t>",
        )
        assert cfg.mqtt.broker_host == "localhost"  # None never erased the local value
        assert cfg.site.name == "Local Site"
        assert cfg.site.elevation == 12.0  # the real KV value still merged

    def test_mqtt_backend_skips_kv_read(self, monkeypatch):
        class _Boom:
            def __init__(self, *a, **k):
                raise AssertionError("NatsBus must not be built for the mqtt backend")

        monkeypatch.setattr("orpheus_common.event_bus_nats.NatsBus", _Boom)
        cfg = OrpheusConfig.from_dict(
            {
                "mqtt": {"broker_host": "localhost"},
                "event_bus": {"backend": "mqtt"},
                "config_service": {"enabled": True},
            },
            source="<t>",
        )
        assert cfg.mqtt.broker_host == "localhost"  # KV distribution is nats-only


NATS_URL = "nats://127.0.0.1:4222"


class TestConfigServiceLive:
    def test_host_reads_base_config_from_kv(self):
        from orpheus_common.config_backend import MISSING, JetStreamKvConfigBackend
        from orpheus_common.config_store import ConfigStore
        from orpheus_common.event_bus_nats import NatsBus

        bus = NatsBus(NATS_URL, client_id="cfgsvc", connect_timeout=2.0)
        try:
            bus.connect()
        except Exception:
            pytest.skip(f"no nats-server on {NATS_URL}")
        bucket = "cfg-" + uuid.uuid4().hex[:8]
        try:
            # Authority seeds the KV (what `orpheus-config push` does).
            store = ConfigStore(
                backend=JetStreamKvConfigBackend(bus, bucket=bucket),
                yaml_getter=lambda _k: MISSING,
            )
            store.set("mqtt.broker_host", "kvhost", author="authority")
        finally:
            bus.disconnect()

        # A host loads config with only nats_url + the flag, and reads the KV value.
        cfg = OrpheusConfig.from_dict(
            {
                "mqtt": {"broker_host": "localhost"},
                "event_bus": {"backend": "nats", "nats_url": NATS_URL},
                "config_service": {"enabled": True, "kv_bucket": bucket},
            },
            source="<live>",
        )
        assert cfg.mqtt.broker_host == "kvhost"
