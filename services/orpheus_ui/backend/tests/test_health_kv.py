"""Tests for the §11 Phase 2 operational-health KV shadow consumer + diff oracle."""

from __future__ import annotations

import asyncio
import contextlib
from unittest.mock import MagicMock

from orpheus_ui import health_kv
from orpheus_ui.auth.models import User


class TestHealthKVCache:
    def test_on_change_stores_then_offline_drops(self):
        c = health_kv.HealthKVCache()
        c.on_change("audio-events", {"status": "online", "agent": "audio-events"})
        assert c.get("audio-events") == {"status": "online", "agent": "audio-events"}
        assert c.keys() == ["audio-events"]
        c.on_change("audio-events", None)  # offline (delete/expiry)
        assert c.get("audio-events") is None
        assert c.keys() == []

    def test_prime_replaces_and_drops_absent_keys(self):
        c = health_kv.HealthKVCache()
        c.on_change("a", {"status": "online"})
        c.on_change("b", {"status": "online"})
        c.prime({"a": {"status": "online"}, "c": {"status": "online"}})
        assert sorted(c.keys()) == ["a", "c"]  # b dropped (absent ⇒ offline)

    def test_view_adds_received_age_and_stale(self):
        c = health_kv.HealthKVCache()
        c.on_change("a", {"status": "online"})
        view = c.view("a")
        assert view["status"] == "online"
        assert "received_age_seconds" in view
        assert view["stale"] is False  # just observed
        assert c.view("missing") is None

    def test_prime_refreshes_receive_time_for_changed_values(self):
        """The kv_watch-dead scenario: values then only ever arrive via prime().
        A CHANGED payload (a fresh heartbeat) must advance the receive-time —
        otherwise a live agent goes permanently stale after 90s."""
        c = health_kv.HealthKVCache()
        c.prime({"a": {"status": "online", "beat": 1}})
        with c._lock:  # backdate past the stale threshold
            c._at["a"] -= health_kv.HEALTH_STALE_AFTER_SECONDS + 10
        assert c.view("a")["stale"] is True
        c.prime({"a": {"status": "online", "beat": 2}})  # fresh heartbeat via floor
        assert c.view("a")["stale"] is False

    def test_prime_keeps_receive_time_for_unchanged_values(self):
        """Re-snapshotting an UNCHANGED value must not reset its age to fresh —
        a dead agent whose last value keeps getting re-listed stays stale."""
        c = health_kv.HealthKVCache()
        c.prime({"a": {"status": "online", "beat": 1}})
        with c._lock:
            c._at["a"] -= health_kv.HEALTH_STALE_AFTER_SECONDS + 10
        c.prime({"a": {"status": "online", "beat": 1}})  # same payload re-listed
        assert c.view("a")["stale"] is True


class TestComputeDiff:
    def test_equal_when_payloads_match_ignoring_envelope(self):
        bus = {"audio-events": {"status": "online", "p50": 12}}
        kv = {  # same payload + the OperationalHealth envelope
            "audio-events": {
                "status": "online",
                "p50": 12,
                "agent": "audio-events",
                "phase": "heartbeat",
                "emitted_at": "2026-06-30T00:00:00Z",
                "schema": 1,
            }
        }
        out = health_kv.compute_health_source_diff(bus, kv)
        assert out["equivalent"] is True
        assert out["divergent"] == 0
        assert out["at_least_one_source_non_empty"] is True

    def test_value_diff_flags_and_includes_both(self):
        out = health_kv.compute_health_source_diff(
            {"audio-events": {"status": "online", "p50": 12}},
            {"audio-events": {"status": "online", "p50": 99, "agent": "audio-events"}},
        )
        assert out["equivalent"] is False
        entry = next(d for d in out["diffs"] if d["key"] == "audio-events")
        assert entry["status"] == "value_diff"
        assert entry["bus"]["p50"] == 12 and entry["kv"]["p50"] == 99

    def test_bus_only_is_the_regression(self):
        out = health_kv.compute_health_source_diff(
            {"audio-events": {"status": "online"}}, {"audio-events": None}
        )
        entry = next(d for d in out["diffs"] if d["key"] == "audio-events")
        assert entry["status"] == "bus_only"  # a source the UI reads that KV lacks
        assert out["equivalent"] is False

    def test_kv_only_is_new_coverage_not_a_regression_but_still_divergent(self):
        out = health_kv.compute_health_source_diff(
            {"bird-detection": None}, {"bird-detection": {"status": "online"}}
        )
        entry = next(d for d in out["diffs"] if d["key"] == "bird-detection")
        assert entry["status"] == "kv_only"

    def test_both_absent_and_empty_guard(self):
        out = health_kv.compute_health_source_diff({"x": None}, {"x": None})
        assert out["at_least_one_source_non_empty"] is False
        assert out["diffs"][0]["status"] == "both_absent"


class TestDiffEndpoint:
    def test_endpoint_compares_bus_and_kv_caches(self):
        from orpheus_ui.api import entities

        # Seed the bus cache (what the UI serves today) + the KV shadow cache.
        with entities._HEALTH_LOCK:
            entities.LATEST_AUDIO_EVENTS_HEALTH = {"status": "online", "p50": 12}
            entities.LATEST_AUTO_DISCOVERY_HEALTH = None
        health_kv.HEALTH_KV_CACHE.prime(
            {
                "audio-events": {"status": "online", "p50": 12, "agent": "audio-events"},
                "bird-detection": {"status": "online", "agent": "bird-detection"},
            }
        )
        try:
            out = entities.get_health_source_diff(user=MagicMock(spec=User))
        finally:
            with entities._HEALTH_LOCK:
                entities.LATEST_AUDIO_EVENTS_HEALTH = None
                entities.LATEST_AUTO_DISCOVERY_HEALTH = None
            health_kv.HEALTH_KV_CACHE.prime({})
        # audio-events present + equal both sides; auto-discovery absent both sides.
        statuses = {d["key"]: d["status"] for d in out["diffs"]}
        assert statuses["audio-events"] == "equal"
        assert statuses["auto-discovery"] == "both_absent"
        # KV coverage gain surfaced (bird-detection has no bus per-agent cache).
        assert "bird-detection" in out["kv_keys"]


class TestPhase3Serving:
    """§11 Phase 3: when promoted (ui.health_source == 'kv'), the health endpoints
    serve from the KV cache; default 'bus' is unchanged (instant, one-flag reversible).
    The branch is monkeypatched directly (the config singleton isn't loadable in the
    test env, and _serve_health_from_kv falls back to bus on any config error)."""

    def test_audio_events_served_from_kv_when_promoted(self, monkeypatch):
        from orpheus_ui.api import entities

        monkeypatch.setattr(entities, "_serve_health_from_kv", lambda: True)
        health_kv.HEALTH_KV_CACHE.prime(
            {"audio-events": {"status": "online", "p50": 5, "agent": "audio-events"}}
        )
        try:
            out = entities.get_audio_events_health(user=MagicMock(spec=User))
        finally:
            health_kv.HEALTH_KV_CACHE.prime({})
        assert out["status"] == "online" and out["p50"] == 5
        assert "received_age_seconds" in out and out["stale"] is False  # KV view shape

    def test_errors_projected_from_kv_when_promoted(self, monkeypatch):
        from orpheus_ui.api import entities

        monkeypatch.setattr(entities, "_serve_health_from_kv", lambda: True)
        health_kv.HEALTH_KV_CACHE.prime(
            {
                "bird-detection": {
                    "agent": "bird-detection",
                    "last_error": "boom",
                    "errors_count": 3,
                },
                "crow-detection": {"agent": "crow-detection"},  # no error -> not listed
            }
        )
        try:
            out = entities.get_recent_errors(limit=50, user=MagicMock(spec=User))
        finally:
            health_kv.HEALTH_KV_CACHE.prime({})
        agents = {e["agent"] for e in out["errors"]}
        assert "bird-detection" in agents
        assert "crow-detection" not in agents  # last-value projection: no error ⇒ absent

    def test_default_bus_source_is_unchanged(self, monkeypatch):
        import time as _time

        from orpheus_ui.api import entities

        monkeypatch.setattr(entities, "_serve_health_from_kv", lambda: False)  # default
        with entities._HEALTH_LOCK:
            entities.LATEST_AUDIO_EVENTS_HEALTH = {"status": "online", "src": "bus"}
            entities.LATEST_AUDIO_EVENTS_HEALTH_AT = _time.monotonic()
        try:
            out = entities.get_audio_events_health(user=MagicMock(spec=User))
        finally:
            with entities._HEALTH_LOCK:
                entities.LATEST_AUDIO_EVENTS_HEALTH = None
        assert out["src"] == "bus"  # served from the bus cache (default), KV ignored


class TestPhase5bSubscriptions:
    """§11 Phase 5b: the UI drops the 5 health subscriptions when serving from KV, but
    the 4 detection subs + entities/animal MUST survive the flip."""

    _DETECTION = {
        "orpheus/audio/motion/events",
        "orpheus/video/motion/events",
        "orpheus/detection/bird/events",
        "orpheus/detection/crow/events",
        "orpheus/entities/animal",
    }
    _HEALTH = {
        "orpheus/system/audio/health",
        "orpheus/system/video/health",
        "orpheus/system/auto-discovery/health",
        "orpheus/system/audio-events/health",
        "orpheus/system/+/health",
    }

    @staticmethod
    def _subscribed(health_source, mock_config):
        from orpheus_ui import main

        client = MagicMock()
        main._subscribe_topics(client, health_source)
        return {c.kwargs["topic_pattern"] for c in client.subscribe.call_args_list}

    def test_bus_source_subscribes_health_and_detection(self, mock_config):
        topics = self._subscribed("bus", mock_config)
        assert self._DETECTION <= topics  # detection always present
        assert self._HEALTH <= topics  # health present when serving from bus

    def test_both_source_keeps_health_subs(self, mock_config):
        topics = self._subscribed("both", mock_config)
        assert self._HEALTH <= topics  # "both" still serves from bus -> keep subs

    def test_kv_source_drops_health_keeps_detection(self, mock_config):
        topics = self._subscribed("kv", mock_config)
        assert self._DETECTION <= topics  # detection subs SURVIVE the flip (the guard)
        assert not (self._HEALTH & topics)  # health subs dropped


class TestBusSetupErrorBoundary:
    """Subscribing is load-bearing; the KV shadow consumer is optional. A failure
    in the optional half must never leave the UI holding a connected bus that is
    subscribed to nothing — that is a dashboard that looks healthy and silently
    serves an ever-staler cache."""

    @staticmethod
    def _config():
        cfg = MagicMock()
        cfg.ui.health_source = "kv"
        cfg.event_bus.backend = "nats"
        cfg.event_bus.nats_url = "nats://127.0.0.1:4222"
        return cfg

    def _run(self, monkeypatch, kv_side_effect, mock_config):
        from orpheus_ui import main

        client = MagicMock()
        monkeypatch.setattr(main, "create_event_bus", lambda *a, **k: client)
        monkeypatch.setattr(main, "_start_health_kv_consumer", kv_side_effect)
        monkeypatch.setattr(main.diagnostics, "set_mqtt_client", lambda c: None)
        monkeypatch.setattr(main.presence, "set_bus", lambda c: None)
        bus = asyncio.run(main._connect_event_bus(self._config()))
        topics = {c.kwargs["topic_pattern"] for c in client.subscribe.call_args_list}
        return bus, client, topics

    def test_kv_consumer_failure_still_subscribes_and_keeps_the_bus(self, monkeypatch, mock_config):
        async def _boom(client, health_source):
            raise RuntimeError("KV bucket unreachable")

        bus, client, topics = self._run(monkeypatch, _boom, mock_config)
        assert bus is client, "the bus was dropped by an optional-path failure"
        # ...and it falls back to bus health rather than a never-fed KV cache.
        assert TestPhase5bSubscriptions._DETECTION <= topics
        assert TestPhase5bSubscriptions._HEALTH <= topics

    def test_kv_consumer_success_drops_health_subs_as_before(self, monkeypatch, mock_config):
        async def _ok(client, health_source):
            return "kv"

        bus, client, topics = self._run(monkeypatch, _ok, mock_config)
        assert bus is client
        assert TestPhase5bSubscriptions._DETECTION <= topics
        assert not (TestPhase5bSubscriptions._HEALTH & topics)

    def test_subscribe_failure_keeps_the_bus_for_its_own_retry(self, monkeypatch, mock_config):
        from orpheus_ui import main

        async def _ok(client, health_source):
            return "bus"

        client = MagicMock()
        client.subscribe.side_effect = RuntimeError("broker refused")
        monkeypatch.setattr(main, "create_event_bus", lambda *a, **k: client)
        monkeypatch.setattr(main, "_start_health_kv_consumer", _ok)
        monkeypatch.setattr(main.diagnostics, "set_mqtt_client", lambda c: None)
        monkeypatch.setattr(main.presence, "set_bus", lambda c: None)
        # The bus survives so its own subscription sweep can re-apply them, and
        # /api/diagnostics/bus can report what is still pending.
        assert asyncio.run(main._connect_event_bus(self._config())) is client

    def test_connect_failure_returns_no_bus(self, monkeypatch, mock_config):
        from orpheus_ui import main

        client = MagicMock()
        client.connect.side_effect = ConnectionError("no broker")
        monkeypatch.setattr(main, "create_event_bus", lambda *a, **k: client)
        assert asyncio.run(main._connect_event_bus(self._config())) is None


class TestServeFromKvGate:
    """Serving-from-KV requires config == "kv" AND a started consumer
    (health_kv.CONSUMER_ACTIVE). Config alone must never route the health
    endpoints at a never-fed empty cache (e.g. health_source="kv" on an mqtt
    backend, or prime/kv_watch failing at boot)."""

    def _cfg(self, health_source):
        cfg = MagicMock()
        cfg.ui.health_source = health_source
        return cfg

    def test_config_kv_but_consumer_inactive_serves_bus(self, monkeypatch):
        from orpheus_ui.api import entities

        monkeypatch.setattr(
            "orpheus_common.config.OrpheusConfig.get_instance", lambda: self._cfg("kv")
        )
        monkeypatch.setattr(health_kv, "CONSUMER_ACTIVE", False)
        assert entities._serve_health_from_kv() is False

    def test_config_kv_and_consumer_active_serves_kv(self, monkeypatch):
        from orpheus_ui.api import entities

        monkeypatch.setattr(
            "orpheus_common.config.OrpheusConfig.get_instance", lambda: self._cfg("kv")
        )
        monkeypatch.setattr(health_kv, "CONSUMER_ACTIVE", True)
        assert entities._serve_health_from_kv() is True

    def test_consumer_active_but_config_bus_serves_bus(self, monkeypatch):
        from orpheus_ui.api import entities

        monkeypatch.setattr(
            "orpheus_common.config.OrpheusConfig.get_instance", lambda: self._cfg("bus")
        )
        monkeypatch.setattr(health_kv, "CONSUMER_ACTIVE", True)
        assert entities._serve_health_from_kv() is False


class TestKvErrorFeedContract:
    """The KV projection of /api/errors/recent must carry EVERY field the
    bus-path entries carry — RecentErrorsPanel dereferences last_seen/count
    unconditionally, so a narrower KV payload crashes the panel on promotion."""

    def test_kv_entries_carry_every_bus_contract_field(self, monkeypatch):
        from orpheus_ui.api import entities

        monkeypatch.setattr(entities, "_serve_health_from_kv", lambda: True)
        # Derive the bus contract from a real bus-path entry, not a hardcoded list.
        with entities._ERROR_FEED_LOCK:
            entities.ERROR_FEED.clear()
        entities._record_agent_error("bus-agent", "bus boom", 2)
        with entities._ERROR_FEED_LOCK:
            bus_keys = set(entities.ERROR_FEED[-1])
            entities.ERROR_FEED.clear()

        health_kv.HEALTH_KV_CACHE.prime(
            {
                "bird-detection": {
                    "agent": "bird-detection",
                    "last_error": "boom",
                    "errors_count": 3,
                    "emitted_at": "2026-07-06T00:00:00+00:00",
                }
            }
        )
        try:
            out = entities.get_recent_errors(limit=50, user=MagicMock(spec=User))
        finally:
            health_kv.HEALTH_KV_CACHE.prime({})
        entry = out["errors"][0]
        assert bus_keys <= set(entry)  # full contract: no field the panel reads is missing
        assert entry["first_seen"] == "2026-07-06T00:00:00+00:00"
        assert entry["last_seen"] == "2026-07-06T00:00:00+00:00"
        assert entry["count"] == 1  # last-value projection has no dedup history

    def test_kv_entry_without_emitted_at_still_carries_the_fields(self, monkeypatch):
        from orpheus_ui.api import entities

        monkeypatch.setattr(entities, "_serve_health_from_kv", lambda: True)
        health_kv.HEALTH_KV_CACHE.prime(
            {"crow-detection": {"agent": "crow-detection", "last_error": "x"}}
        )
        try:
            out = entities.get_recent_errors(limit=50, user=MagicMock(spec=User))
        finally:
            health_kv.HEALTH_KV_CACHE.prime({})
        entry = out["errors"][0]
        assert entry["first_seen"] == "" and entry["last_seen"] == ""  # str, never None
        assert entry["count"] == 1


class TestResnapshotLoop:
    """The re-snapshot loop is the boot-failure retry mechanism: it re-primes,
    re-attaches the kv_watch if it never started, and promotes CONSUMER_ACTIVE —
    a boot-time broker blip must not kill the shadow consumer for the process
    lifetime."""

    async def test_loop_recovers_from_boot_blip_and_promotes(self, monkeypatch, mock_config):
        from orpheus_ui import main

        calls = {"n": 0}

        def kv_list(bucket):
            calls["n"] += 1
            if calls["n"] == 1:  # the boot blip
                raise RuntimeError("broker unreachable")
            return {"audio-events": {"status": "online"}}

        bus = MagicMock()
        bus.kv_list.side_effect = kv_list
        monkeypatch.setattr(main, "_mqtt_client", bus)
        monkeypatch.setattr(main, "_health_kv_watch_started", False)
        monkeypatch.setattr(health_kv, "CONSUMER_ACTIVE", False)
        monkeypatch.setattr(health_kv, "HEALTH_RESNAPSHOT_SECONDS", 0.01)

        task = asyncio.create_task(main._health_resnapshot_loop())
        try:
            for _ in range(500):
                await asyncio.sleep(0.01)
                if health_kv.CONSUMER_ACTIVE:
                    break
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            health_kv.HEALTH_KV_CACHE.prime({})

        assert health_kv.CONSUMER_ACTIVE is True
        assert main._health_kv_watch_started is True  # watch re-attached by the loop
        bus.kv_watch.assert_called_once_with(
            health_kv.HEALTH_BUCKET,
            ">",
            health_kv.HEALTH_KV_CACHE.on_change,
            create=False,
        )
