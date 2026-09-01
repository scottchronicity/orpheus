"""Storage-volume registry — the storage spaces Orpheus tracks.

A single, extensible list of the filesystems we care about, plus a helper
that reads each one's current usage. Today that's the **system** root (`/`)
and the **orpheus** data drive (`get_data_root()`); add a row here when a
new storage space appears (a second data disk, an archive mount, …) and
every consumer — the live readout, the history sampler, the trend chart —
picks it up automatically.

A "volume" is identified by a stable ``key`` (used as the history table's
key, so don't rename casually), a human ``label``, and a filesystem
``path``. Two keys may resolve to the same physical filesystem (e.g. if
`/data/orpheus` lives on the root partition); that's fine — usage is
reported honestly per path.
"""

from __future__ import annotations

import shutil
from typing import Any, Optional

from orpheus_common.logging import get_logger
from orpheus_common.storage import get_data_root

logger = get_logger(__name__)


def _volume_specs() -> list[tuple[str, str, str]]:
    """The (key, label, path) specs for every tracked storage space.

    Kept as a function (not a module constant) because the orpheus data
    path is resolved at call time from config/env via ``get_data_root()``.
    """
    return [
        ("system", "System", "/"),
        ("orpheus", "Orpheus Data", str(get_data_root())),
    ]


def _usage_for(path: str) -> dict[str, Optional[Any]]:
    """Current total/used/free/percent for one path, or an error dict."""
    try:
        usage = shutil.disk_usage(path)
        percent = round(usage.used / usage.total * 100, 1) if usage.total else 0.0
        return {
            "total": usage.total,
            "used": usage.used,
            "free": usage.free,
            "percent": percent,
            "ok": True,
            "error": None,
        }
    except OSError as exc:
        # Path missing / not mounted — report rather than crash the whole
        # registry (a single unmounted archive disk shouldn't break the
        # system volume's reading).
        logger.warning("disk_usage failed for volume path", path=path, error=str(exc))
        return {
            "total": None,
            "used": None,
            "free": None,
            "percent": 0.0,
            "ok": False,
            "error": str(exc),
        }


def list_storage_volumes() -> list[dict[str, Any]]:
    """Every tracked storage space with its current usage.

    Returns one dict per volume: ``key``, ``label``, ``path`` plus the
    ``_usage_for`` fields (total/used/free/percent/ok/error). Order is
    stable (registry order) so UIs render consistently.
    """
    volumes: list[dict[str, Any]] = []
    for key, label, path in _volume_specs():
        volumes.append({"key": key, "label": label, "path": path, **_usage_for(path)})
    return volumes
