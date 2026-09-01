"""UI consumer of the operational-health KV plane (§11 Phase 2 — shadow + oracle).

Shadow-reads the ``orpheus_health`` KV bucket into an in-process cache (a ``kv_watch``
primed + kept honest by a periodic snapshot floor), so this phase can prove KV == bus
via ``/api/diagnostics/health-source-diff`` while the UI keeps **serving from the
bus**. The periodic re-snapshot is the correctness floor: the served/compared value
never depends on a long-lived watch staying alive (``kv_watch`` stops permanently on
error). Promotion to serving-from-KV is Phase 3; this module changes no serving path.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

from orpheus_common.actor import (
    ENVELOPE_FIELDS,
    HEALTH_STALE_AFTER_SECONDS,
    OperationalHealth,
)
from orpheus_common.actor import HEALTH_BUCKET as HEALTH_BUCKET  # re-export (consumer contract)

HEALTH_RESNAPSHOT_SECONDS = 30.0  # the correctness-floor cadence

# The bucket, envelope keys, and staleness floor are the WRITER's contract
# (orpheus_common.actor.operational_health) — imported, never re-declared, so
# the two sides of the health plane cannot fork. Receive fields are computed
# per-source on this side only.
_ENVELOPE_FIELDS = frozenset(ENVELOPE_FIELDS)
_RECEIVE_FIELDS = frozenset({"received_age_seconds", "stale"})


class HealthKVCache:
    """Thread-safe latest-health-per-agent cache fed from the KV plane."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values: Dict[str, dict] = {}
        self._at: Dict[str, float] = {}

    def on_change(self, key: str, value: Optional[dict]) -> None:
        """``kv_watch`` callback: ``None`` ⇒ offline (drop the key); else store + stamp."""
        with self._lock:
            if value is None:
                self._values.pop(key, None)
                self._at.pop(key, None)
            else:
                self._values[key] = value
                self._at[key] = time.monotonic()

    def prime(self, snapshot: Dict[str, dict]) -> None:
        """Re-snapshot floor: replace the cache with the current KV state. Keeps the
        existing receive-time only for keys whose value is UNCHANGED (so re-snapshotting
        an unchanged value doesn't reset its age to fresh, but a fresh heartbeat that
        arrives via the floor — the kv_watch-dead case, where prime() is the only feed —
        does advance the age and clears ``stale``); stamps new/changed keys now. Keys
        absent from the snapshot (TTL-expired / deleted) drop ⇒ offline."""
        now = time.monotonic()
        with self._lock:
            self._at = {
                k: (self._at.get(k, now) if self._values.get(k) == snapshot[k] else now)
                for k in snapshot
            }
            self._values = {k: dict(v) for k, v in snapshot.items()}

    def get(self, key: str) -> Optional[dict]:
        """The raw stored envelope for ``key`` (or None if absent)."""
        with self._lock:
            v = self._values.get(key)
            return dict(v) if v is not None else None

    def view(self, key: str) -> Optional[dict]:
        """The served shape (used once Phase 3 promotes serving to KV): payload +
        ``received_age_seconds`` + ``stale``, or None if absent (⇒ offline)."""
        with self._lock:
            v = self._values.get(key)
            if v is None:
                return None
            age = time.monotonic() - self._at.get(key, 0.0)
            out = dict(v)
            out["received_age_seconds"] = round(age, 1)
            out["stale"] = age > HEALTH_STALE_AFTER_SECONDS
            return out

    def keys(self) -> List[str]:
        with self._lock:
            return sorted(self._values)

    def snapshot(self) -> Dict[str, dict]:
        """All current ``key -> envelope`` (copied). For the error-feed projection."""
        with self._lock:
            return {k: dict(v) for k, v in self._values.items()}


# Process-wide cache (mirrors entities.py's module-global health caches). Populated
# by the lifespan consumer when ui.health_source is "kv"/"both" + the backend has KV.
HEALTH_KV_CACHE = HealthKVCache()

# True only once the lifespan consumer has actually FED the cache (a successful
# prime; main.py sets it, the re-snapshot loop re-asserts it). Serving-from-KV
# (Phase 3) requires config == "kv" AND this flag — config alone must never route
# the health endpoints at a never-fed empty cache (e.g. ui.health_source="kv" on
# an mqtt backend, or a broker outage at boot).
CONSUMER_ACTIVE: bool = False


def prime_cache(bus: Any, cache: HealthKVCache = HEALTH_KV_CACHE) -> None:
    """Re-snapshot the KV bucket into the cache (initial prime + the periodic floor).
    Raises on a KV/transport error so the caller can log + keep the last good cache.
    Reads via ``OperationalHealth.snapshot()`` — the writer's own consumer surface —
    like ``api/presence.py`` does, instead of raw bucket access."""
    cache.prime(OperationalHealth(bus).snapshot())


def _comparable(payload: Optional[dict]) -> Optional[dict]:
    """Strip envelope + receive fields so the underlying health payload compares equal
    across the bus and KV sources."""
    if payload is None:
        return None
    return {
        k: v
        for k, v in payload.items()
        if k not in _ENVELOPE_FIELDS and k not in _RECEIVE_FIELDS
    }


def compute_health_source_diff(
    bus: Dict[str, Optional[dict]], kv: Dict[str, Optional[dict]]
) -> Dict[str, Any]:
    """The Phase-2 equivalence oracle. Each arg maps ``key -> payload`` (``None`` =
    absent in that source). Per key, flags ``value_diff``, ``bus_only`` (the worst
    regression — a source the UI serves that KV lacks), and ``kv_only`` (new coverage);
    guards that at least one source is non-empty. ``equivalent`` ⇒ safe to promote."""
    keys = sorted(set(bus) | set(kv))
    diffs: List[Dict[str, Any]] = []
    divergent = 0
    for key in keys:
        b = _comparable(bus.get(key))
        k = _comparable(kv.get(key))
        if b is None and k is None:
            status = "both_absent"
        elif b is None:
            status = "kv_only"  # KV covers more agents than the 2 bus caches; not a regression
        elif k is None:
            status = "bus_only"  # REGRESSION: a source the UI reads that KV is missing
        elif b == k:
            status = "equal"
        else:
            status = "value_diff"
        entry: Dict[str, Any] = {"key": key, "status": status}
        if status in ("bus_only", "kv_only", "value_diff"):
            divergent += 1
            if status == "value_diff":
                entry["bus"] = b
                entry["kv"] = k
        diffs.append(entry)
    any_nonempty = any(v is not None for v in list(bus.values()) + list(kv.values()))
    return {
        "diffs": diffs,
        "divergent": divergent,
        "equivalent": divergent == 0,
        "at_least_one_source_non_empty": any_nonempty,
    }
