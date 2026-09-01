"""Layered, versioned configuration store ([FEATURE] Database-Backed Config —
foundation).

Today config is a single ``orpheus.yaml``. This adds the layered + versioned
core a multi-station future needs: a resolver that reads **env > backend > YAML**,
plus an audit trail (who changed what, when) and a change notification on the
bus. It is a STANDALONE, opt-in primitive — it does NOT rewire
``OrpheusConfig.get_instance`` (the high-blast-radius delegation is a deferred
follow-on, tracked in the backlog). With no overrides written, ``get`` falls
straight through to the YAML layer.

The override layer's *persistence* is behind the ``ConfigBackend`` seam
(``config_backend.py``, ADR 0018): ``SqliteConfigBackend`` is the default
(byte-identical to before), and a JetStream-KV backend can plug in for
distribution without touching this resolver. This seam is parallel to the
EventBus backend, NOT coupled to the message transport.

Constraints: additive (the SQLite backend's own ``config.db`` file + table,
nothing existing touched), Python 3.9. The bus is optional/injected so the store
is usable (and testable) without one.
"""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

from orpheus_common.config_backend import (
    MISSING as _MISSING,
)
from orpheus_common.config_backend import (
    ConfigBackend,
    ConfigVersion,
    SqliteConfigBackend,
)
from orpheus_common.logging import get_logger
from orpheus_common.utils.time import utc_now_iso

logger = get_logger(__name__)

# A change-notification event (not retained state): key + new value per set().
CONFIG_CHANGED_TOPIC = "orpheus/system/config_changed"

# Re-exported for back-compat: callers import these from config_store.
__all__ = ["CONFIG_CHANGED_TOPIC", "ConfigBackend", "ConfigStore", "ConfigVersion"]


def _env_key(key: str) -> str:
    """Dotted key -> env var, matching the legacy Config convention."""
    return "ORPHEUS_" + key.replace(".", "_").upper()


def _yaml_from_orpheus_config(key: str) -> Any:
    """Default YAML layer: dotted lookup into the loaded OrpheusConfig.to_dict().
    Lazy-imported so this module stays cheap and avoids an import cycle."""
    from orpheus_common.config import OrpheusConfig

    data: Any = OrpheusConfig.get_instance().to_dict()
    for part in key.split("."):
        if isinstance(data, dict) and part in data:
            data = data[part]
        else:
            return _MISSING
    return data


class ConfigStore:
    """Layered (env > backend > YAML) config resolver over a pluggable, versioned
    override backend. Not thread-safe; drive one instance per thread."""

    def __init__(
        self,
        *,
        db_path: Optional[Path] = None,
        backend: Optional[ConfigBackend] = None,
        yaml_getter: Optional[Callable[[str], Any]] = None,
        bus: Any = None,
        topic: str = CONFIG_CHANGED_TOPIC,
    ) -> None:
        # Persistence is behind the ConfigBackend seam. Default = SQLite (its own
        # config.db, orthogonal to detection data so a config-DB problem can never
        # corrupt detections). ``db_path`` configures the default backend; pass an
        # explicit ``backend`` to distribute config (e.g. JetStream-KV, ADR 0018).
        self._backend: ConfigBackend = backend or SqliteConfigBackend(db_path)
        # Default YAML layer reads the loaded OrpheusConfig; injectable for tests.
        self._yaml_getter = yaml_getter if yaml_getter is not None else _yaml_from_orpheus_config
        self._bus = bus
        self._topic = topic
        self._subscribers: List[Tuple[str, Callable[[str, Any], None]]] = []

    def get(self, key: str, default: Any = None, *, env_override: bool = True) -> Any:
        """Resolve ``key`` by precedence: env var (``ORPHEUS_<KEY>``) > backend
        override (latest version) > YAML base > ``default``.

        env values are returned as the RAW string (no type coercion) — unlike
        ``OrpheusConfig.get``, which coerces to the default's type. There's no
        reference type at this layer, so callers coerce at the call site; the
        eventual ``get_instance`` delegation must reconcile this difference.
        Backend and YAML values keep their stored types, and an explicit ``None``
        at either layer is honoured — only a truly-absent key falls to ``default``."""
        if env_override:
            env_val = os.environ.get(_env_key(key))
            if env_val is not None:
                return env_val  # env wins; raw string, no coercion
        override = self._backend.current(key)
        if override is not _MISSING:
            return override
        yaml_val = self._yaml_getter(key)
        if yaml_val is not _MISSING:
            return yaml_val
        return default

    def set(self, key: str, value: Any, author: str = "system") -> ConfigVersion:
        """Write a new version of ``key`` to the override layer, notify the bus,
        and fire matching subscribers. Returns the recorded ``ConfigVersion``."""
        changed_at = utc_now_iso()
        version = self._backend.put(key, value, author, changed_at)
        record = ConfigVersion(
            key=key, value=value, author=author, changed_at=changed_at, version=version
        )
        self._notify(record)
        return record

    def history(self, key: str, limit: int = 10) -> List[ConfigVersion]:
        """The audit trail for ``key``, newest first (up to ``limit`` entries)."""
        return self._backend.history(key, limit)

    def subscribe(self, key_pattern: str, callback: Callable[[str, Any], None]) -> None:
        """Register ``callback(key, value)`` to fire on a ``set`` whose key
        matches ``key_pattern`` (fnmatch globbing, e.g. ``audio.*``)."""
        self._subscribers.append((key_pattern, callback))

    def _notify(self, record: ConfigVersion) -> None:
        if self._bus is not None:
            try:
                self._bus.publish(self._topic, {"key": record.key, "value": record.value})
            except Exception:
                logger.exception("Failed to publish config change", key=record.key)
        for pattern, callback in self._subscribers:
            if fnmatch.fnmatch(record.key, pattern):
                try:
                    callback(record.key, record.value)
                except Exception:
                    logger.exception("Config subscriber callback failed", key=record.key)
