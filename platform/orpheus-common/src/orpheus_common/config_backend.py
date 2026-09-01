"""Pluggable persistence/distribution backend for ``ConfigStore`` (ADR 0018).

``ConfigStore`` owns the layered ``env > backend > YAML`` resolution plus the
change-notify; the *persistence* of the override layer (and, later, its
cross-host distribution) is this seam. ``SqliteConfigBackend`` is the default and
keeps the versioned audit trail in ``config.db`` — byte-identical to the
pre-extraction ``ConfigStore``. A future ``JetStreamKvConfigBackend`` plugs in
here without touching ``ConfigStore``: this seam is **parallel to the EventBus
backend**, NOT coupled to the message transport (see ADR 0018 — config capability
is a first-class concern, not a "bastard child" of the bus).

Constraints unchanged from ConfigStore: additive (its own ``config.db`` file +
``config_versions`` table, nothing existing touched), Python 3.9, stdlib + the
shared ``open_connection`` only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional, Protocol, runtime_checkable

from orpheus_common.detection.database import open_connection
from orpheus_common.storage import get_data_root

# Sentinel: distinguishes "no override for this key" from a stored ``None``.
# Defined here (the persistence layer) and re-exported by config_store so the
# resolver and the backend compare against the *same* object identity.
MISSING = object()


@dataclass(frozen=True)
class ConfigVersion:
    """One audit-trail entry for a config key (a write to the override layer)."""

    key: str
    value: Any
    author: str
    changed_at: str  # ISO-8601
    version: int  # 1-based, monotonic per key


@runtime_checkable
class ConfigBackend(Protocol):
    """Persistence (and, for distributed backends, distribution) of the config
    override layer. The resolver/notify in ``ConfigStore`` is transport-agnostic;
    everything that touches storage lives behind this Protocol."""

    def current(self, key: str) -> Any:
        """The current override value for ``key`` (highest version), or
        ``MISSING`` if the key has no override."""
        ...

    def put(self, key: str, value: Any, author: str, changed_at: str) -> int:
        """Persist a new version of ``key`` and return its 1-based, per-key
        monotonic version number. Atomic per call (single writer)."""
        ...

    def history(self, key: str, limit: int) -> List[ConfigVersion]:
        """The audit trail for ``key``, newest first (up to ``limit`` entries)."""
        ...


class SqliteConfigBackend:
    """Default backend: the versioned override layer in a SQLite ``config.db``.

    Config overrides are orthogonal to detection data -> their own file, so a
    config-DB problem can never corrupt detections. This is the audit-of-record
    (ADR 0018): the full, unbounded ``config_versions`` trail lives here even once
    a KV backend serves distribution."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._db_path = Path(db_path) if db_path else (get_data_root() / "config.db")
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        conn = open_connection(self._db_path)
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS config_versions ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT NOT NULL, "
                "value_json TEXT NOT NULL, author TEXT NOT NULL, "
                "changed_at TEXT NOT NULL, version INTEGER NOT NULL)"
            )
            # UNIQUE so a duplicate (key, version) fails loudly rather than
            # producing two "latest" rows (single-writer, so no legit collision).
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_config_versions_key "
                "ON config_versions(key, version)"
            )
            conn.commit()
        finally:
            conn.close()

    def current(self, key: str) -> Any:
        conn = open_connection(self._db_path)
        try:
            cur = conn.execute(
                "SELECT value_json FROM config_versions WHERE key = ? "
                "ORDER BY version DESC LIMIT 1",
                (key,),
            )
            row = cur.fetchone()
        finally:
            conn.close()
        if row is None:
            return MISSING
        return json.loads(row[0])

    def put(self, key: str, value: Any, author: str, changed_at: str) -> int:
        # Compute next version + insert on ONE connection so the per-key counter
        # stays atomic (single writer; the UNIQUE index is the backstop).
        conn = open_connection(self._db_path)
        try:
            cur = conn.execute(
                "SELECT COALESCE(MAX(version), 0) FROM config_versions WHERE key = ?",
                (key,),
            )
            version = int(cur.fetchone()[0]) + 1
            conn.execute(
                "INSERT INTO config_versions (key, value_json, author, changed_at, version) "
                "VALUES (?, ?, ?, ?, ?)",
                (key, json.dumps(value), author, changed_at, version),
            )
            conn.commit()
        finally:
            conn.close()
        return version

    def history(self, key: str, limit: int) -> List[ConfigVersion]:
        conn = open_connection(self._db_path)
        try:
            cur = conn.execute(
                "SELECT key, value_json, author, changed_at, version FROM config_versions "
                "WHERE key = ? ORDER BY version DESC LIMIT ?",
                (key, int(limit)),
            )
            rows = cur.fetchall()
        finally:
            conn.close()
        return [
            ConfigVersion(
                key=r[0],
                value=json.loads(r[1]),
                author=r[2],
                changed_at=r[3],
                version=int(r[4]),
            )
            for r in rows
        ]


# Default KV bucket holding the distributed config override layer (ADR 0018).
_CONFIG_KV_BUCKET = "orpheus_config"


class JetStreamKvConfigBackend:
    """``ConfigBackend`` that distributes the override layer over a JetStream KV
    bucket (ADR 0018) — a pure consumer of the EventBus KV surface
    (``kv_get``/``kv_put``), so any KV-capable bus works and this stays parallel to,
    not coupled with, the message transport.

    For cross-host config: ONE authority writes (its own ``orpheus-config push`` /
    ``ConfigStore.set``), MANY hosts read — so hosts don't copy identical YAML.

    SQLite stays the **audit-of-record**: the KV ABC has no history iteration, so
    ``history()`` exposes only the *current* version (the full unbounded trail lives
    in ``SqliteConfigBackend`` on the authority). The deployment is single-writer
    (one authority), so the read-modify-write version bump in ``put()`` is race-free
    as intended; the per-key ``version`` is stored inside the value envelope.

    Each KV value is an envelope ``{value, author, changed_at, version}`` so an
    explicitly-stored ``None`` is distinguishable from an absent key (``kv_get``
    returns ``None`` only when the key is absent; the envelope is never ``None``).
    ``current()`` may raise if the broker is unreachable (``kv_get`` does not mask an
    outage as "unset") — the ``get_instance`` KV layer is where broker-unreachable
    falls back to local YAML (a deferred follow-on)."""

    def __init__(self, bus: Any, *, bucket: str = _CONFIG_KV_BUCKET) -> None:
        self._bus = bus
        self._bucket = bucket

    def current(self, key: str) -> Any:
        envelope = self._bus.kv_get(self._bucket, key)
        if envelope is None:
            return MISSING  # absent (kv_get returns None only for absent)
        return envelope.get("value", MISSING)

    def put(self, key: str, value: Any, author: str, changed_at: str) -> int:
        prev = self._bus.kv_get(self._bucket, key)
        version = int(prev["version"]) + 1 if prev and "version" in prev else 1
        self._bus.kv_put(
            self._bucket,
            key,
            {"value": value, "author": author, "changed_at": changed_at, "version": version},
        )
        return version

    def history(self, key: str, limit: int) -> List[ConfigVersion]:
        # KV keeps no per-key history (SQLite is the audit-of-record); expose only
        # the current version so callers get a consistent, non-empty trail shape.
        envelope = self._bus.kv_get(self._bucket, key)
        if envelope is None:
            return []
        return [
            ConfigVersion(
                key=key,
                value=envelope.get("value"),
                author=str(envelope.get("author", "")),
                changed_at=str(envelope.get("changed_at", "")),
                version=int(envelope.get("version", 1)),
            )
        ]
