"""Tests for the layered/versioned ConfigStore ([FEATURE] Database-Backed Config)."""

from pathlib import Path
from unittest.mock import Mock

from orpheus_common.config_store import (
    _MISSING,
    CONFIG_CHANGED_TOPIC,
    ConfigStore,
    ConfigVersion,
)


def _store(tmp_path: Path, *, yaml=None, bus=None) -> ConfigStore:
    # Inject a YAML layer dict so tests don't depend on a loaded OrpheusConfig.
    # The getter returns _MISSING for absent keys (the module's "no value" sentinel).
    yaml = yaml or {}
    return ConfigStore(
        db_path=tmp_path / "config.db",
        yaml_getter=lambda k: yaml.get(k, _MISSING),
        bus=bus,
    )


class TestLayering:
    def test_falls_through_to_default(self, tmp_path: Path) -> None:
        assert _store(tmp_path).get("nope", "fallback") == "fallback"

    def test_yaml_layer_used_when_no_override(self, tmp_path: Path) -> None:
        store = _store(tmp_path, yaml={"audio.gain": 0.5})
        assert store.get("audio.gain") == 0.5

    def test_db_overrides_yaml(self, tmp_path: Path) -> None:
        store = _store(tmp_path, yaml={"audio.gain": 0.5})
        store.set("audio.gain", 0.9)
        assert store.get("audio.gain") == 0.9

    def test_env_overrides_db_and_yaml(self, tmp_path: Path, monkeypatch) -> None:
        store = _store(tmp_path, yaml={"audio.gain": 0.5})
        store.set("audio.gain", 0.9)
        monkeypatch.setenv("ORPHEUS_AUDIO_GAIN", "1.5")
        assert store.get("audio.gain") == "1.5"  # env wins (raw string)
        # env_override=False bypasses env and falls back to the DB layer.
        assert store.get("audio.gain", env_override=False) == 0.9

    def test_stored_none_override_is_respected(self, tmp_path: Path) -> None:
        # A DB override of None must beat the YAML layer (not be treated as absent).
        store = _store(tmp_path, yaml={"k": "yaml"})
        store.set("k", None)
        assert store.get("k", "default") is None

    def test_explicit_yaml_none_is_honored(self, tmp_path: Path) -> None:
        # A YAML key explicitly set to None returns None (symmetric with the DB
        # layer + matches OrpheusConfig.get); only a truly-absent key uses default.
        store = _store(tmp_path, yaml={"k": None})
        assert store.get("k", "default") is None

    def test_env_value_is_raw_string_not_coerced(self, tmp_path: Path, monkeypatch) -> None:
        # DELIBERATE divergence from OrpheusConfig.get (which coerces to the
        # default's type): env values come back as raw strings. The deferred
        # get_instance delegation must reconcile this.
        monkeypatch.setenv("ORPHEUS_AUDIO_GAIN", "1.5")
        val = _store(tmp_path, yaml={"audio.gain": 0.5}).get("audio.gain", 0.0)
        assert val == "1.5" and isinstance(val, str)


class TestVersioning:
    def test_set_increments_version_per_key(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        assert store.set("k", 1).version == 1
        assert store.set("k", 2).version == 2
        assert store.set("other", 9).version == 1  # per-key counter

    def test_history_newest_first_and_limited(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        for i in range(5):
            store.set("k", i, author=f"a{i}")
        hist = store.history("k", limit=3)
        assert [h.version for h in hist] == [5, 4, 3]
        assert hist[0].value == 4 and hist[0].author == "a4"
        assert all(isinstance(h, ConfigVersion) for h in hist)

    def test_history_empty_for_unknown_key(self, tmp_path: Path) -> None:
        assert _store(tmp_path).history("never") == []

    def test_complex_values_roundtrip(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        store.set("k", {"a": [1, 2], "b": True})
        assert store.get("k") == {"a": [1, 2], "b": True}

    def test_persists_across_instances(self, tmp_path: Path) -> None:
        ConfigStore(db_path=tmp_path / "config.db", yaml_getter=lambda k: _MISSING).set("k", 7)
        store2 = ConfigStore(db_path=tmp_path / "config.db", yaml_getter=lambda k: _MISSING)
        assert store2.get("k") == 7


class TestNotifications:
    def test_set_publishes_to_bus(self, tmp_path: Path) -> None:
        bus = Mock()
        _store(tmp_path, bus=bus).set("audio.gain", 0.9)
        bus.publish.assert_called_once_with(
            CONFIG_CHANGED_TOPIC, {"key": "audio.gain", "value": 0.9}
        )

    def test_subscriber_fires_on_matching_key(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        seen = []
        store.subscribe("audio.*", lambda k, v: seen.append((k, v)))
        store.set("audio.gain", 0.9)
        store.set("video.fps", 30)  # non-matching → no callback
        assert seen == [("audio.gain", 0.9)]

    def test_subscriber_failure_does_not_break_set(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        store.subscribe("*", lambda k, v: (_ for _ in ()).throw(RuntimeError("boom")))
        # A bad subscriber must not stop the write or raise out of set().
        assert store.set("k", 1).version == 1

    def test_bus_failure_does_not_break_set(self, tmp_path: Path) -> None:
        bus = Mock()
        bus.publish.side_effect = RuntimeError("broker down")
        assert _store(tmp_path, bus=bus).set("k", 1).version == 1


class TestEnvLayer:
    def test_env_key_convention(self, tmp_path: Path, monkeypatch) -> None:
        # Dotted key -> ORPHEUS_<UPPER_WITH_UNDERSCORES>.
        monkeypatch.setenv("ORPHEUS_CORRELATION_WINDOW_SECONDS", "9")
        assert _store(tmp_path).get("correlation.window_seconds") == "9"
