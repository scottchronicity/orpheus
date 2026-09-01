"""ConfigBackend seam (ADR 0018): persistence is pluggable, parallel to EventBus.

The default SqliteConfigBackend behavior is covered through ConfigStore in
test_config_store.py. These tests assert the *seam* itself: the default conforms
to the Protocol, and ConfigStore delegates persistence to an injected backend
(the property a JetStream-KV backend relies on) while keeping env/YAML/notify in
the resolver."""

from typing import Any, List

from orpheus_common.config_backend import (
    MISSING,
    ConfigBackend,
    ConfigVersion,
    SqliteConfigBackend,
)
from orpheus_common.config_store import ConfigStore


def test_sqlite_backend_is_a_configbackend(tmp_path):
    # runtime_checkable Protocol: the default backend structurally conforms.
    assert isinstance(SqliteConfigBackend(tmp_path / "config.db"), ConfigBackend)


class _FakeBackend:
    """An in-memory backend — proves ConfigStore needs nothing SQLite-specific."""

    def __init__(self) -> None:
        self.versions: dict[str, List[ConfigVersion]] = {}

    def current(self, key: str) -> Any:
        hist = self.versions.get(key)
        return hist[-1].value if hist else MISSING

    def put(self, key: str, value: Any, author: str, changed_at: str) -> int:
        hist = self.versions.setdefault(key, [])
        version = len(hist) + 1
        hist.append(ConfigVersion(key, value, author, changed_at, version))
        return version

    def history(self, key: str, limit: int) -> List[ConfigVersion]:
        return list(reversed(self.versions.get(key, [])))[:limit]


def test_injected_backend_is_used_for_persistence():
    fake = _FakeBackend()
    store = ConfigStore(backend=fake, yaml_getter=lambda k: MISSING)

    rec = store.set("audio.gain", 0.9)
    assert rec.version == 1
    # The value round-trips through the injected backend, not SQLite.
    assert store.get("audio.gain") == 0.9
    assert fake.versions["audio.gain"][-1].value == 0.9
    assert store.set("audio.gain", 1.1).version == 2
    assert [v.value for v in store.history("audio.gain")] == [1.1, 0.9]


def test_resolver_layers_stay_above_the_backend():
    # env still beats the backend; absent key still falls through to YAML.
    fake = _FakeBackend()
    store = ConfigStore(backend=fake, yaml_getter=lambda k: 7 if k == "from.yaml" else MISSING)
    store.set("k", "from-backend")

    import os

    os.environ["ORPHEUS_K"] = "from-env"
    try:
        assert store.get("k") == "from-env"  # env > backend
        assert store.get("k", env_override=False) == "from-backend"
        assert store.get("from.yaml") == 7  # backend MISSING -> YAML
        assert store.get("nope", "fallback") == "fallback"
    finally:
        del os.environ["ORPHEUS_K"]
